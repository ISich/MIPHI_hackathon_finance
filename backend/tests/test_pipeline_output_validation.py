"""Procedure-output contract regressions using the real pipeline and pinned core.

These in-process tests replace only Linux input-file opening and installed-VCS
verification. They do not exercise the supervisor, OS isolation or HTTP worker.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from dd_backend import pipeline


class Events:
    def __init__(self):
        self.items = []

    def send(self, **payload):
        self.items.append(payload)


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    files = {}
    digest = hashlib.sha256()
    for side, decision in (("BEFORE", "REJECT"), ("AFTER", "APPROVE")):
        data = json.dumps({"appData": {"application_id": "APP1"},
                           "decisionResult": {"decision": decision}}).encode()
        path = tmp_path / f"{side}.json"
        path.write_bytes(data)
        files[side.lower()] = {"APP1.json": str(path)}
        digest.update(f"{side}/APP1.json\0".encode())
        digest.update(hashlib.sha256(data).digest())
    (snapshot / "inputs.json").write_text(json.dumps({**files, "root": str(tmp_path),
        "mode": "dirs", "fingerprint": digest.hexdigest()}))
    # Linux-specific descriptor/path enforcement is covered by backend integration tests.
    monkeypatch.setattr(pipeline, "_read_verified", lambda path, *a, **kw: path.read_bytes())
    monkeypatch.setattr(pipeline, "verify_builtin_runtime", lambda cfg: None)
    return tmp_path


def configure(run_dir, slot=None, mutation=""):
    procedures = {s: {"source": "builtin", "params": {}, "code_sha256": "0" * 64}
                  for s in ("normalize", "compare", "segments", "aggregate")}
    if slot:
        procedures[slot]["source"] = "workspace"
        code = {
            "normalize": "from decision_diff.core import normalize as original\nfrom decision_diff.configs import REAL\ndef normalize(document, app_id, source, params):\n    rows = original(document, app_id, source, REAL)\n",
            "compare": "from decision_diff.core import compare as original\ndef compare(before, after, params):\n    rows = original(before, after)\n",
            "segments": "from decision_diff.segments import build_segment as original\ndef build_segment(before, after, app_id, params):\n    row = original(before, after, app_id)\n",
        }[slot]
        result = "row" if slot == "segments" else "rows"
        (run_dir / "snapshot" / f"{slot}.py").write_text(code + mutation + f"    return {result}\n")
    (run_dir / "snapshot" / "config.json").write_text(json.dumps({"procedures": procedures}))


@pytest.mark.parametrize("slot,mutation", [
    ("normalize", "    rows[0]['APP_ID'] = 'OTHER'\n"),
    ("normalize", "    rows[0]['SOURCE'] = 'AFTER'\n"),
    ("normalize", "    rows.append(dict(rows[0]))\n"),
    ("normalize", "    rows[0]['VALUE'] = 123\n"),
    ("normalize", "    rows[0]['PATH'] = ''\n"),
    ("compare", "    rows[0]['APP_ID'] = 'OTHER'\n"),
    ("compare", "    rows.append(dict(rows[0]))\n"),
    ("compare", "    rows[0]['DIFF_FLAG'] = str(rows[0]['DIFF_FLAG'])\n"),
    ("compare", "    rows[0]['VALUE_AFTER'] = 123\n"),
    ("segments", "    row['DECISION_CHANGED'] = 0\n"),
    ("segments", "    row['DECISION_CHANGED'] = '1'\n"),
    ("segments", "    row['PRODUCTS'] = ['unexpected']\n"),
])
def test_invalid_procedure_output_fails_before_artifact_publication(prepared, slot, mutation):
    configure(prepared, slot, mutation)
    with pytest.raises(pipeline.StageFailure) as caught:
        pipeline.run(prepared, Events())
    assert caught.value.code == "OUTPUT_SCHEMA_INVALID"
    assert slot in caught.value.message
    assert not list((prepared / "artifacts").glob("*.csv"))
    assert not (prepared / "artifacts" / "mart.duckdb").exists()


@pytest.mark.parametrize("slot", [None, "normalize", "compare", "segments"])
def test_valid_builtin_and_workspace_procedures_still_materialize_mart(prepared, slot):
    configure(prepared, slot)
    result = pipeline.run(prepared, Events())
    assert result["summary"]["total_apps"] == 1
    assert result["summary"]["changed_apps"] == 1
    assert result["summary"]["decision_changed_apps"] == 1
    assert result["summary"]["mart_tables"]["base_membership"] > 0
    assert result["summary"]["membership_validation"]["ok"] is True

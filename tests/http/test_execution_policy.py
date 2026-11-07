"""Custom-code execution policy (NFR-006, BACKEND_NIGHT_TASK §4D) with execution canaries (CR #3).

Every custom script writes a canary file at import time AND when its entrypoint runs. In builtin-only mode:
storing/uploading/editing code must not execute it, and every attempt to run it (4 procedure slots, checks in a
Run, check-only run) must be refused with the documented 403 CUSTOM_EXECUTION_DISABLED - and no canary may
appear. In trusted-local the same canary scripts DO leave canaries (positive control: the probe works).
The server shares the host with the tests (loopback is enforced), so it can reach the canary directory.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest

from support.http_api import assert_envelope

SLOTS = ("normalize", "compare", "segments", "aggregate")
REFUSAL = "CUSTOM_EXECUTION_DISABLED"

ENTRY = {
    "normalize": "def normalize(document, app_id, source, params):\n    _hit('run')\n    return []\n",
    "compare": "def compare(before_rows, after_rows, params):\n    _hit('run')\n    return []\n",
    "segments": "def build_segment(before_doc, after_doc, app_id, params):\n    _hit('run')\n    return {'APP_ID': app_id}\n",
    "aggregate": "def aggregate(comparison_rows, segments, params):\n    _hit('run')\n    return {'pivot_facts': [], 'summary': {}}\n",
    "check": ("def run(mart, params=None):\n    _hit('run')\n    return []\n"
              "CHECK = {'id': 'qa_canary_%(tag)s', 'label': 'canary', 'params': {}, 'entrypoint': run}\n"),
}


def canary_code(kind: str, folder: Path, tag: str) -> str:
    head = (f"import pathlib as _p\nCANARY = _p.Path({str(folder)!r})\n"
            f"def _hit(what):\n    (CANARY / ('{kind}-{tag}-' + what)).write_text('x')\n_hit('import')\n")
    return head + ENTRY[kind] % {"tag": tag}


@pytest.fixture()
def canary_dir(tmp_path):
    folder = tmp_path / "canary"
    folder.mkdir()
    folder.chmod(0o777)
    return folder


def _assert_no_canary(folder: Path, wait: float = 3.0):
    time.sleep(wait)  # give a (wrongly) started job time to import/execute
    assert sorted(p.name for p in folder.iterdir()) == []


@pytest.fixture()
def builtin_only(execution_mode):
    if execution_mode != "builtin-only":
        pytest.skip("policy refusal applies to builtin-only servers")


def test_store_upload_edit_do_not_execute_code(api_a, canary_dir, builtin_only):
    tag = uuid.uuid4().hex[:8]
    created = api_a.script("check", canary_code("check", canary_dir, tag))
    assert created.status_code == 201, created.text
    up = api_a.http.post("/api/scripts/upload", data={"kind": "check", "name": "canary-up"},
                         files={"file": ("canary_up.py", canary_code("check", canary_dir, tag + "u").encode(),
                                         "text/x-python")})
    assert up.status_code == 201, up.text
    edit = api_a.put(f"/api/scripts/{created.json()['script_id']}", {"code": canary_code("check", canary_dir, tag + "e")})
    assert edit.status_code == 200, edit.text
    _assert_no_canary(canary_dir, wait=1.0)


@pytest.mark.parametrize("slot", SLOTS)
def test_custom_procedure_run_is_refused_and_never_executes(api_a, examples_root, canary_dir, builtin_only, slot):
    script = api_a.script(slot, canary_code(slot, canary_dir, uuid.uuid4().hex[:8]))
    assert script.status_code == 201, script.text
    ds = api_a.dataset(examples_root, "files", "I32554354_other.json", "I32554354.json")
    cfg = api_a.post("/api/configurations", {"name": "canary", "dataset_id": ds["dataset_id"],
                                             "slots": {slot: {"script_id": script.json()["script_id"]}}}, key=None)
    if cfg.status_code != 201:  # refusing already at configuration time is equally acceptable
        assert_envelope(cfg, 403, REFUSAL)
    else:
        assert_envelope(api_a.start_run(cfg.json()["config_id"]), 403, REFUSAL)
    _assert_no_canary(canary_dir)


def test_custom_check_in_run_is_refused_and_never_executes(api_a, examples_root, canary_dir, builtin_only):
    script = api_a.script("check", canary_code("check", canary_dir, uuid.uuid4().hex[:8]))
    ds = api_a.dataset(examples_root, "files", "I32554354_other.json", "I32554354.json")
    cfg = api_a.post("/api/configurations", {"name": "canary", "dataset_id": ds["dataset_id"],
                                             "checks": [{"script_id": script.json()["script_id"]}]}, key=None)
    if cfg.status_code != 201:
        assert_envelope(cfg, 403, REFUSAL)
    else:
        assert_envelope(api_a.start_run(cfg.json()["config_id"]), 403, REFUSAL)
    _assert_no_canary(canary_dir)


def test_custom_check_only_run_is_refused_and_never_executes(api_a, completed_example_run, canary_dir, builtin_only):
    script = api_a.script("check", canary_code("check", canary_dir, uuid.uuid4().hex[:8]))
    builtin = [{"script_id": s["script_id"]} for s in api_a.builtin_checks()]
    r = api_a.post(f"/api/runs/{completed_example_run['final']['run_id']}/check-runs",
                   {"checks": builtin + [{"script_id": script.json()["script_id"]}]})
    assert_envelope(r, 403, REFUSAL)
    _assert_no_canary(canary_dir)


def test_canary_probe_detects_execution_in_trusted_local(api_a, completed_example_run, canary_dir, execution_mode):
    """Positive control: on a trusted-local server the canary check really leaves canary files."""
    if execution_mode != "trusted-local":
        pytest.skip("positive control needs a trusted-local server")
    tag = uuid.uuid4().hex[:8]
    script = api_a.script("check", canary_code("check", canary_dir, tag))
    cr = api_a.post(f"/api/runs/{completed_example_run['final']['run_id']}/check-runs",
                    {"checks": [{"script_id": script.json()["script_id"]}]})
    assert cr.status_code == 202, cr.text
    api_a.wait(f"/api/check-runs/{cr.json()['check_run_id']}")
    names = {p.name for p in canary_dir.iterdir()}
    assert f"check-{tag}-import" in names and f"check-{tag}-run" in names, names

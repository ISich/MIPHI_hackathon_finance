"""Synthetic but schema-faithful SPR response fixtures and a REAL pipeline runner.

No test doubles here: `run_real_pipeline` writes JSON files to BEFORE/AFTER
folders, runs the pinned core CLI (`python -m decision_diff.cli`) as a
subprocess and loads its CSV outputs with the D4 `storage.build_database`.
The resulting DuckDB file is opened with the real `DuckDBMart`.

The fixtures are internal team fixtures (method from PRD AC-11), not the
organizers' baseline and not a replacement for the open dataset.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

Doc = dict[str, Any]


def base_doc(app_id: str, *, decision: str = "APPROVE", product_id: int = 15210,
             product_name: str = "KUPI_KUPI", pd_model: str = "ML_MICRO_LOAN_V1",
             cutoff: str = "CUT_2026", score_okb: int = 710,
             rules: list[tuple[str, bool]] | None = None,
             feature_score_okb: int | None = None) -> Doc:
    """One application response shaped like the open dataset (decision_diff REAL config)."""
    rules = rules if rules is not None else [("RESTRICTED_REGIONS", False), ("AGELOW@21", False)]
    features: dict[str, Any] = {"age": 30, "sumActiveDeals": 1000}
    if feature_score_okb is not None:
        features["score_okb"] = feature_score_okb
    return {
        "appData": {"application_id": app_id, "request_id": f"req-{app_id}",
                    "createDateTime": "2026-01-01T00:00:00Z"},
        "decisionResult": {
            "decision": decision,
            "available_offers": ([{"product_id": product_id, "product_name": product_name,
                                   "rank": 1, "type": "standard"}] if decision == "APPROVE" else []),
            "product_trials": [{
                "product_name": product_name, "product_id": product_id, "tariff": 190,
                "routing_method": "referal", "partner_id": 1, "partner_name": "P",
                "partner_type": "CURRENT",
                "rules": [{"name": n, "description": f"rule {n}", "hit": h} for n, h in rules],
                "decision": decision, "rejectReason": None, "rejectReasonCode": None,
                "scoring": {"scoreModels": [{"value": 0.6, "modelName": pd_model,
                                             "type": "APPROVAL_PROBABILITY"}],
                            "pd": {"modelName": pd_model, "value": 0.6}},
                "epr": 1000, "calculationType": "standard",
                "cutOff": {"name": cutoff, "value": 0.5},
            }],
            "scoring": [{"features": features, "modelName": pd_model, "value": [0.1, 0.2]}],
        },
        "characteristics": {"score_okb": score_okb, "score_equ": 700},
        "ext_data": [{"body": {"action": "score_okb", "id": app_id,
                               "params": {"data": score_okb, "error": False, "ok": True}},
                      "characteristics": {"score_okb": score_okb}, "status": 200}],
        "product_catalog": [{"is_new_mfo": False, "mfo_id": "MFO_A", "product_id": product_id,
                             "routing_method": "referal"}],
        "tariff_matrix": [{"mfo_id": "MFO_A", "product_id": product_id, "tariff": 190}],
    }


def pair(app_id: str, mutate_after: Callable[[Doc], None] | None = None,
         mutate_before: Callable[[Doc], None] | None = None, **kwargs: Any) -> tuple[str, Doc, Doc]:
    before = base_doc(app_id, **kwargs)
    after = copy.deepcopy(before)
    if mutate_before:
        mutate_before(before)
    if mutate_after:
        mutate_after(after)
    return app_id, before, after


@dataclass
class PipelineRun:
    root: Path
    out: Path
    db: Path
    cli_stdout: str
    cli_returncode: int

    def summary(self) -> dict[str, Any]:
        return json.loads((self.out / "summary.json").read_text(encoding="utf-8"))

    def issues(self) -> dict[str, Any]:
        return json.loads((self.out / "issues.json").read_text(encoding="utf-8"))


def write_dataset(root: Path, pairs: list[tuple[str, Doc, Doc]]) -> tuple[Path, Path]:
    before_dir, after_dir = root / "BEFORE", root / "AFTER"
    before_dir.mkdir(parents=True, exist_ok=True)
    after_dir.mkdir(parents=True, exist_ok=True)
    for app_id, before, after in pairs:
        (before_dir / f"{app_id}.json").write_text(json.dumps(before, ensure_ascii=False), encoding="utf-8")
        (after_dir / f"{app_id}.json").write_text(json.dumps(after, ensure_ascii=False), encoding="utf-8")
    return before_dir, after_dir


def run_cli(before: Path, after: Path, out: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "decision_diff.cli", "--before", str(before), "--after", str(after),
         "--out", str(out)],
        capture_output=True, text=True, timeout=300, check=False,
    )


def run_real_pipeline(root: Path, pairs: list[tuple[str, Doc, Doc]]) -> PipelineRun:
    """JSON files -> real core CLI -> real D4 storage (DuckDB)."""
    from decision_diff.storage import build_database

    before_dir, after_dir = write_dataset(root / "data", pairs)
    out = root / "out"
    proc = run_cli(before_dir, after_dir, out)
    if proc.returncode != 0:
        raise AssertionError(f"core CLI failed: {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    db = out / "mart.duckdb"
    build_database(out, db)
    return PipelineRun(root=root, out=out, db=db, cli_stdout=proc.stdout, cli_returncode=proc.returncode)

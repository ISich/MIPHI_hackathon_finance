"""CR3 #4 regression: the full-dataset acceptance must not pass without the expected executed checks."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("full_dataset_run", ROOT / "scripts" / "full_dataset_run.py")
fdr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fdr)

IDS = {"ar_drop_by_product", "attribute_new_loss", "external_score_drift", "stop_factor_disappeared",
       "target_model_changed"}


def _report(executions, completeness="COMPLETE", status="PUBLISHED"):
    return {"run": {"status": "COMPLETED"}, "api_equals_cli": True, "report_status": status,
            "checks": {"completeness": completeness, "executions": executions}}


def _ok(ids):
    return [{"check_id": i, "execution_status": "SUCCEEDED"} for i in sorted(ids)]


def test_complete_run_is_accepted():
    assert fdr.acceptance_problems(_report(_ok(IDS)), IDS) == []


def test_zero_executions_is_rejected():
    # The d198c32 condition all(...) over an empty list accepted exactly this report.
    assert all(e["execution_status"] == "SUCCEEDED" for e in [])
    assert fdr.acceptance_problems(_report([]), IDS)


def test_missing_or_extra_check_is_rejected():
    assert fdr.acceptance_problems(_report(_ok(IDS - {"target_model_changed"})), IDS)
    assert fdr.acceptance_problems(_report(_ok(IDS | {"other"})), IDS)


def test_incomplete_or_unpublished_report_is_rejected():
    assert fdr.acceptance_problems(_report(_ok(IDS), completeness="INCOMPLETE"), IDS)
    assert fdr.acceptance_problems(_report(_ok(IDS), status="PENDING"), IDS)
    assert fdr.acceptance_problems(_report(_ok(IDS), completeness="NO_CHECKS_SELECTED"), IDS)


def test_organizer_ids_come_from_check_files(tmp_path):
    for i in IDS:
        (tmp_path / f"check_{i}.py").write_text("")
    assert fdr.organizer_check_ids(tmp_path) == IDS

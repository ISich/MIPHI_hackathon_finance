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


SUMMARY = {"total_apps": 2, "changed_apps": 1, "decision_changed_apps": 1, "changed_attributes": 3,
           "change_types": {"SAME": 1}, "approval_rate_before": 0.5, "approval_rate_after": 0.5}


def _ok(ids):
    return [{"check_id": i, "execution_status": "SUCCEEDED"} for i in sorted(ids)]


def _full(executions=None, completeness="COMPLETE", status="PUBLISHED", **over):
    """A fully valid report; every test changes exactly one thing, so it fails for that reason only."""
    rep = {"run": {"status": "COMPLETED"}, "api_equals_cli": True, "report_status": status,
           "checks": {"completeness": completeness,
                      "executions": _ok(IDS) if executions is None else executions},
           "cli": {"returncode": 0}, "api_summary": dict(SUMMARY), "cli_summary": dict(SUMMARY),
           "http_errors": [], "cli_issues": {"missing_before": [], "missing_after": [], "failed": []},
           "files": {"BEFORE_MASTER": 2, "AFTER_BETA": 2},
           "dataset_revision": {"pairs": 2, "missing_before": [], "missing_after": []}}
    rep.update(over)
    return rep


def _only(problems, needle):
    assert len(problems) == 1 and needle in problems[0], problems


def test_complete_run_is_accepted():
    assert fdr.acceptance_problems(_full(), IDS) == []


def test_zero_executions_is_rejected():
    # The d198c32 condition all(...) over an empty list accepted exactly this report.
    assert all(e["execution_status"] == "SUCCEEDED" for e in [])
    _only(fdr.acceptance_problems(_full(executions=[]), IDS), "executed checks")


def test_missing_or_extra_check_is_rejected():
    _only(fdr.acceptance_problems(_full(executions=_ok(IDS - {"target_model_changed"})), IDS), "executed checks")
    _only(fdr.acceptance_problems(_full(executions=_ok(IDS | {"other"})), IDS), "executed checks")


def test_incomplete_or_unpublished_report_is_rejected():
    _only(fdr.acceptance_problems(_full(completeness="INCOMPLETE"), IDS), "completeness")
    _only(fdr.acceptance_problems(_full(completeness="NO_CHECKS_SELECTED"), IDS), "completeness")
    _only(fdr.acceptance_problems(_full(status="PENDING"), IDS), "report status")


def test_organizer_ids_come_from_check_files(tmp_path):
    for i in IDS:
        (tmp_path / f"check_{i}.py").write_text("")
    assert fdr.organizer_check_ids(tmp_path) == IDS


def test_failed_cli_with_missing_values_is_rejected():
    """CR(4b74f18) #4: CLI failed and API values are None -> None == None must not count as agreement."""
    nones = {k: None for k in SUMMARY}
    rep = _full(cli={"returncode": 1}, api_summary=nones, cli_summary={})
    assert all(rep["api_summary"].get(k) == rep["cli_summary"].get(k) for k in SUMMARY)  # the old comparison
    problems = fdr.acceptance_problems(rep, IDS)
    assert any("returncode" in p for p in problems) and any("missing" in p for p in problems)


def test_http_errors_are_rejected():
    _only(fdr.acceptance_problems(_full(http_errors=["GET /api/runs/x/summary -> 500"]), IDS), "HTTP errors")


def test_zero_total_apps_is_rejected():
    problems = fdr.acceptance_problems(_full(api_summary={**SUMMARY, "total_apps": 0}), IDS)
    assert problems and all("total_apps" in p for p in problems), problems


def test_partial_dataset_is_rejected():
    """CR5 #1: CLI exits 0 and summaries agree, but only the surviving pairs were processed."""
    issues = {"missing_before": [], "missing_after": ["P2.json"], "failed": [{"file": "P3.json", "reason": "bad"}]}
    problems = fdr.acceptance_problems(_full(cli_issues=issues), IDS)
    assert any("missing_after" in p for p in problems) and any("failed" in p for p in problems)


def test_totals_must_match_input_pairs():
    problems = fdr.acceptance_problems(_full(files={"BEFORE_MASTER": 3, "AFTER_BETA": 3},
                                             dataset_revision={"pairs": 3, "missing_before": [], "missing_after": []}),
                                       IDS)
    assert problems and all("!= input pairs 3" in p for p in problems), problems
    assert fdr.acceptance_problems(_full(files={"BEFORE_MASTER": 2, "AFTER_BETA": 1}), IDS)
    assert fdr.acceptance_problems(_full(dataset_revision={"pairs": 2, "missing_before": [],
                                                           "missing_after": ["X"]}), IDS)
    assert fdr.acceptance_problems(_full(cli_issues=None), IDS)

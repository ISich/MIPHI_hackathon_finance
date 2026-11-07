"""Business FAIL vs execution error vs 0 rows over HTTP (FR-025, AC-11, AC-14, PRD §10), real core + real checks."""
from __future__ import annotations

import pytest


ROW = ('{"LABEL": "qa", "SOURCE": "AFTER", "ARGUMENT": "%s", "CNT": 1, "TOTAL": mart.total_apps(), '
       '"METRIC": 0.5, "APP_IDS": [], "RESULT": "%s", "CONFIDENCE": "HIGH"}')


def _check(check_id: str, body: str) -> str:
    return body + f'\nCHECK = {{"id": "{check_id}", "label": "{check_id}", "params": {{}}, "entrypoint": run}}\n'


CUSTOM = {
    "qa_biz_fail": _check("qa_biz_fail", "def run(mart, params=None):\n    return [" + ROW % ("biz", "FAIL") + "]\n"),
    "qa_raises": _check("qa_raises", "def run(mart, params=None):\n    raise RuntimeError('qa boom')\n"),
    "qa_empty": _check("qa_empty", "def run(mart, params=None):\n    return []\n"),
    "qa_invalid": _check("qa_invalid", "def run(mart, params=None):\n    return [{'RESULT': 'ERROR'}]\n"),
    "qa_sleep": _check("qa_sleep", "import time\ndef run(mart, params=None):\n    time.sleep(60)\n    return []\n"),
}


def test_events_dataset_builtin_checks_fail_with_expected_app_ids(api_a, fixture_root):
    """AC-11 over HTTP: unchanged organizer checks on event fixtures -> FAIL rows, all executions SUCCEEDED."""
    root, _ = fixture_root
    ds = api_a.dataset(root, "dirs", "events/BEFORE", "events/AFTER")
    final = api_a.wait(f"/api/runs/{api_a.start_run(api_a.config(ds['dataset_id'])['config_id']).json()['run_id']}")
    assert final["status"] == "COMPLETED", final
    doc = api_a.get(f"/api/runs/{final['run_id']}/checks").json()
    assert doc["completeness"] == "COMPLETE"
    assert {e["execution_status"] for e in doc["executions"]} == {"SUCCEEDED"} and len(doc["executions"]) == 5
    fails = {(r["LABEL"], tuple(r["APP_IDS"])) for r in doc["checks"] if r["RESULT"] == "FAIL"}
    ids = {a for _, apps in fails for a in apps}
    assert {"EV01", "EV02", "EV03", "EV04", "EV05"} <= ids, fails
    assert "EV06" not in ids


@pytest.fixture(scope="module")
def outcomes(api_a, completed_example_run, execution_mode):
    created = {}
    for cid, code in CUSTOM.items():
        r = api_a.script("check", code)
        assert r.status_code == 201, r.text
        created[cid] = r.json()["script_id"]
    run_id = completed_example_run["final"]["run_id"]
    r = api_a.post(f"/api/runs/{run_id}/check-runs", {"checks": [{"script_id": s} for s in created.values()]})
    return {"resp": r, "mode": execution_mode, "ids": created, "run_id": run_id}


# Refusal in builtin-only mode: see test_execution_policy.py (canary-based, CR #3).


@pytest.fixture(scope="module")
def finished(api_a, outcomes):
    if outcomes["mode"] != "trusted-local":
        pytest.skip("custom check execution disabled on this server (builtin-only) - see refusal test")
    assert outcomes["resp"].status_code == 202, outcomes["resp"].text
    cr = api_a.wait(f"/api/check-runs/{outcomes['resp'].json()['check_run_id']}", timeout=180)
    doc = api_a.get(f"/api/reports/{cr['report_id']}/checks").json()
    by_script = {e["script_id"]: e for e in cr["executions"]}
    return {"cr": cr, "doc": doc, "by_script": by_script, "ids": outcomes["ids"]}


def _ex(finished, cid):
    return finished["by_script"][finished["ids"][cid]]


def test_business_fail_is_row_and_succeeded(finished):
    ex = _ex(finished, "qa_biz_fail")
    assert ex["execution_status"] == "SUCCEEDED" and ex["rows_count"] == 1
    assert [r["RESULT"] for r in finished["doc"]["checks"] if r["ARGUMENT"] == "biz"] == ["FAIL"]


def test_exception_is_error_status_not_a_row(finished):
    ex = _ex(finished, "qa_raises")
    assert ex["execution_status"] == "ERROR" and ex["rows_count"] == 0


def test_zero_rows_is_success_not_fake_pass(finished):
    ex = _ex(finished, "qa_empty")
    assert ex["execution_status"] == "SUCCEEDED" and ex["rows_count"] == 0
    assert not [r for r in finished["doc"]["checks"] if r.get("LABEL") == "qa_empty"]


def test_invalid_output_status(finished):
    assert _ex(finished, "qa_invalid")["execution_status"] == "INVALID_OUTPUT"


def test_timeout_status(finished):
    assert _ex(finished, "qa_sleep")["execution_status"] == "TIMEOUT"


def test_report_marked_incomplete_but_published(finished):
    assert finished["cr"]["status"] == "COMPLETED"
    assert finished["doc"]["completeness"] == "INCOMPLETE"
    rows = finished["doc"]["checks"]
    assert {r["RESULT"] for r in rows} <= {"PASS", "FAIL"}

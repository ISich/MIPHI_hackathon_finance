"""Slices F/G: check orchestration over the REAL D4 DuckDBMart and immutable report identities.

No test doubles: checks run against the per-run mart built by decision_diff.storage.
"""
import json
import subprocess
import sys

import pytest

from conftest import make_client, wait_check_run, wait_run
from helpers import config, demo_dataset, idem, start_run


def _row(result="FAIL", **over):
    row = {"LABEL": "t", "SOURCE": "AFTER", "ARGUMENT": "a", "CNT": 1, "TOTAL": 1, "METRIC": 1.0,
           "APP_IDS": ["I32554354"], "RESULT": result, "CONFIDENCE": "LOW"}
    row.update(over)
    return row


def _check_code(cid, body, params="{}"):
    return f"DEFAULTS = {params}\n\ndef run(mart, params=None):\n{body}\n\nCHECK = {{'id': '{cid}', 'label': '{cid}', 'params': DEFAULTS, 'entrypoint': run}}\n"


CHECKS = {
    "business_fail": _check_code("business_fail", f"    assert mart.total_apps() == 1\n    return [{_row('FAIL', LABEL='business_fail')!r}]"),
    "raises": _check_code("raises", "    raise ValueError('check bug')"),
    "empty": _check_code("empty", "    return []"),
    "bad_result": _check_code("bad_result", f"    return [{_row('MAYBE')!r}]"),
    "foreign_ids": _check_code("foreign_ids", f"    return [{_row('PASS', APP_IDS=['NOT_IN_RUN'])!r}]"),
    "bad_filter": _check_code("bad_filter", "    return [] if mart.count(no_such_filter=1) else []"),
    "dup_a": _check_code("dupe", "    return []"),
    "dup_b": _check_code("dupe", f"    return [{_row('PASS')!r}]"),
    "import_error": "import not_a_real_module_xyz\n",
    "no_check": "x = 1\n",
    "slow": _check_code("slow", "    import time\n    time.sleep(30)\n    return []"),
    "params": _check_code("params", "    p = {**DEFAULTS, **(params or {})}\n    return [dict(" + repr(_row('PASS', LABEL='params')) + ", ARGUMENT=str(p['x']))]", "{'x': 1}"),
}


@pytest.fixture
def trusted(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_CHECK_TIMEOUT_SECONDS", "4")
    with make_client() as c:
        yield c


def _scripts(c, names):
    out = {}
    for n in names:
        r = c.post("/api/scripts", json={"kind": "check", "name": n, "code": CHECKS[n]})
        assert r.status_code == 201, r.json()
        out[n] = r.json()["script_id"]
    return out


def test_organizer_checks_on_real_fixture_match_d4_cli(client, env, tmp_path):
    ds = demo_dataset(client)
    done = wait_run(client, start_run(client, config(client, ds["dataset_id"])["config_id"]).json()["run_id"])
    assert done["status"] == "COMPLETED" and done["checks_completeness"] == "COMPLETE"
    report = client.get(f"/api/runs/{done['run_id']}/checks").json()
    assert report["report_id"] == done["initial_report_id"]
    assert len(report["executions"]) == 5
    assert {e["execution_status"] for e in report["executions"]} == {"SUCCEEDED"}
    # Independent reference: core CLI + D4 analytics_cli on the same files.
    core = env["core"]
    out = tmp_path / "ref"
    subprocess.run([sys.executable, "-m", "decision_diff.cli", "--before", str(core / "examples/I32554354_other.json"),
                    "--after", str(core / "examples/I32554354.json"), "--out", str(out)], check=True, capture_output=True)
    subprocess.run([sys.executable, "-m", "decision_diff.analytics_cli", "--data", str(out), "--checks", str(core / "checks")],
                   check=True, capture_output=True)
    ref = json.loads((out / "checks_report.json").read_text())
    key = lambda r: json.dumps(r, sort_keys=True)
    assert sorted(map(key, report["checks"])) == sorted(map(key, ref["checks"]))
    assert report["summary"] == ref["summary"]
    html = client.get(f"/api/reports/{report['report_id']}/checks.html")
    assert html.status_code == 200 and "<table>" in html.text
    assert f"/runs/{done['run_id']}/reports/{report['report_id']}" in html.text


def test_execution_statuses_are_distinct_from_business_results(trusted):
    c = trusted
    ds = demo_dataset(c)
    names = ["business_fail", "raises", "empty", "bad_result", "foreign_ids", "bad_filter", "dup_a", "dup_b",
             "import_error", "no_check", "slow", "params"]
    ids = _scripts(c, names)
    checks = [{"script_id": ids[n]} for n in names]
    checks[-1]["params"] = {"x": 42}
    done = wait_run(c, start_run(c, config(c, ds["dataset_id"], checks=checks)["config_id"]).json()["run_id"], timeout=120)
    assert done["status"] == "COMPLETED"  # business FAIL and check errors do not fail the data run
    assert done["checks_completeness"] == "INCOMPLETE"
    rep = c.get(f"/api/runs/{done['run_id']}/checks").json()
    by = {names[int(e["slot"].split("-")[1]) - 1]: e for e in rep["executions"]}
    expected = {"business_fail": "SUCCEEDED", "raises": "ERROR", "empty": "SUCCEEDED", "bad_result": "INVALID_OUTPUT",
                "foreign_ids": "INVALID_OUTPUT", "bad_filter": "ERROR", "dup_a": "SUCCEEDED", "dup_b": "DUPLICATE_ID",
                "import_error": "IMPORT_ERROR", "no_check": "CONTRACT_ERROR", "slow": "TIMEOUT", "params": "SUCCEEDED"}
    assert {k: v["execution_status"] for k, v in by.items()} == expected
    assert by["empty"]["rows_count"] == 0 and by["raises"]["rows_count"] == 0
    assert by["business_fail"]["rows_count"] == 1 and by["params"]["params"]["x"] == 42
    # Only real rows: one business FAIL + one PASS from params; no fabricated PASS/FAIL for errors/empty.
    assert sorted((r["LABEL"], r["RESULT"]) for r in rep["checks"]) == [("business_fail", "FAIL"), ("params", "PASS")]
    assert [r["ARGUMENT"] for r in rep["checks"] if r["LABEL"] == "params"] == ["42"]
    diag_checks = {d["check"] for d in rep["diagnostics"]}
    assert {"raises", "bad_filter", "dupe", "slow"} <= diag_checks
    assert all("/" not in d.get("file", "") for d in rep["diagnostics"])
    assert c.get("/health").status_code == 200


def test_check_only_run_creates_new_report_and_keeps_old_one(trusted):
    c = trusted
    ds = demo_dataset(c)
    ids = _scripts(c, ["business_fail", "empty"])
    done = wait_run(c, start_run(c, config(c, ds["dataset_id"], checks=[{"script_id": ids["empty"]}])["config_id"]).json()["run_id"])
    run_id, first_report = done["run_id"], done["initial_report_id"]
    before_meta = c.get(f"/api/reports/{first_report}").json()
    before_doc = c.get(f"/api/reports/{first_report}/checks").json()
    summary_before = c.get(f"/api/runs/{run_id}/summary").json()

    h = idem()
    r = c.post(f"/api/runs/{run_id}/check-runs", json={"checks": [{"script_id": ids["empty"]}, {"script_id": ids["business_fail"]}]}, headers=h)
    assert r.status_code == 202, r.json()
    cr = r.json()
    again = c.post(f"/api/runs/{run_id}/check-runs", json={"checks": [{"script_id": ids["empty"]}, {"script_id": ids["business_fail"]}]}, headers=h)
    assert again.json()["check_run_id"] == cr["check_run_id"]
    assert cr["check_run_id"] != done["initial_check_run_id"] and cr["report_id"] != first_report
    finished = wait_check_run(c, cr["check_run_id"])
    assert finished["status"] == "COMPLETED" and finished["dataset_revision_id"] == done["dataset_revision_id"]
    new_doc = c.get(f"/api/reports/{cr['report_id']}/checks").json()
    assert [r["RESULT"] for r in new_doc["checks"]] == ["FAIL"]
    # old report and run-level aliases unchanged
    assert c.get(f"/api/reports/{first_report}").json() == before_meta
    assert c.get(f"/api/reports/{first_report}/checks").json() == before_doc
    assert c.get(f"/api/runs/{run_id}/checks").json()["report_id"] == first_report
    assert c.get(f"/api/runs/{run_id}/summary").json() == summary_before
    reports = c.get(f"/api/runs/{run_id}/reports").json()
    assert reports["initial_report_id"] == first_report
    assert [x["report_id"] for x in reports["items"]] == [first_report, cr["report_id"]]
    code = c.get(f"/api/check-runs/{cr['check_run_id']}/code/check-02").json()
    assert "business_fail" in code["code"]


def test_check_runs_need_completed_run_and_respect_safe_mode(client):
    ds = demo_dataset(client)
    cfg = config(client, ds["dataset_id"], checks=[])
    run = start_run(client, cfg["config_id"]).json()
    r = client.post(f"/api/runs/{run['run_id']}/check-runs", json={"checks": []}, headers=idem())
    if r.status_code != 202:
        assert r.status_code == 409 and r.json()["code"] == "NOT_READY"
    done = wait_run(client, run["run_id"])
    custom = client.post("/api/scripts", json={"kind": "check", "name": "c", "code": CHECKS["empty"]}).json()
    r = client.post(f"/api/runs/{done['run_id']}/check-runs", json={"checks": [{"script_id": custom["script_id"]}]},
                    headers=idem())
    assert r.status_code == 403 and r.json()["code"] == "CUSTOM_EXECUTION_DISABLED"
    assert len(client.get(f"/api/runs/{done['run_id']}/reports").json()["items"]) == 1


def test_report_not_ready_before_publication(client):
    ds = demo_dataset(client)
    run = start_run(client, config(client, ds["dataset_id"])["config_id"]).json()
    r = client.get(f"/api/reports/{run['initial_report_id']}/checks")
    if r.status_code != 200:
        assert r.status_code == 409 and r.json()["code"] == "NOT_READY"
    assert client.get(f"/api/reports/{run['initial_report_id']}").json()["status"] in ("PENDING", "PUBLISHED")
    wait_run(client, run["run_id"])

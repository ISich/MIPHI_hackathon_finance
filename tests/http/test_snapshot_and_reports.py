"""Snapshot immutability (FR-027, AC-16/18) and check-only report identity (FR-026, api.md Report identity)."""
from __future__ import annotations

import hashlib

import pytest

from support.http_api import known_defect


CHECK_V1 = '''
def run(mart, params=None):
    return [{"LABEL": "qa v1", "SOURCE": "AFTER", "ARGUMENT": "v1", "CNT": 0, "TOTAL": mart.total_apps(),
             "METRIC": 0.0, "APP_IDS": [], "RESULT": "PASS", "CONFIDENCE": "HIGH"}]
CHECK = {"id": "qa_snapshot", "label": "qa snapshot", "params": {}, "entrypoint": run}
'''
CHECK_V2 = CHECK_V1.replace("qa v1", "qa v2").replace('"v1"', '"v2"')


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_config_and_code_snapshot_survive_script_edit(api_a, examples_root, execution_mode):
    script = api_a.script("check", CHECK_V1)
    assert script.status_code == 201, script.text
    sid = script.json()["script_id"]
    ds = api_a.dataset(examples_root, "files", "I32554354_other.json", "I32554354.json")
    cfg = api_a.config(ds["dataset_id"], checks=[{"script_id": sid}])
    if execution_mode != "trusted-local":
        pytest.skip("snapshot of custom code needs trusted-local; builtin-only refusal: test_execution_policy.py")
    accepted = api_a.start_run(cfg["config_id"])
    assert accepted.status_code == 202, accepted.text
    run_id = accepted.json()["run_id"]
    assert api_a.put(f"/api/scripts/{sid}", {"code": CHECK_V2}).status_code == 200  # edit right after accept
    final = api_a.wait(f"/api/runs/{run_id}")
    assert final["status"] == "COMPLETED", final
    snap = api_a.get(f"/api/runs/{run_id}/code/check-01").json()
    assert snap["code_sha256"] == _sha(CHECK_V1) and "qa v1" in snap["code"]
    rows = api_a.get(f"/api/runs/{run_id}/checks").json()["checks"]
    assert [r["ARGUMENT"] for r in rows if r["LABEL"].startswith("qa")] == ["v1"]
    assert api_a.get(f"/api/configurations/{cfg['config_id']}").json() == cfg
    # the NEXT run uses the new snapshot
    run2 = api_a.start_run(cfg["config_id"]).json()["run_id"]
    api_a.wait(f"/api/runs/{run2}")
    assert api_a.get(f"/api/runs/{run2}/code/check-01").json()["code_sha256"] == _sha(CHECK_V2)


def test_initial_report_is_stable_and_check_only_creates_new_identity(api_a, completed_example_run):
    run = completed_example_run["final"]
    run_id, initial = run["run_id"], run["initial_report_id"]
    before_doc = api_a.get(f"/api/runs/{run_id}/checks").json()
    before_html = api_a.get(f"/api/reports/{initial}/checks.html").text
    before_summary = api_a.get(f"/api/runs/{run_id}/summary").json()
    assert before_doc["report_id"] == initial

    builtin = [{"script_id": s["script_id"]} for s in api_a.builtin_checks()]
    assert len(builtin) == 5
    r = api_a.post(f"/api/runs/{run_id}/check-runs", {"checks": builtin})
    assert r.status_code == 202, r.text
    cr = r.json()
    assert cr["report_id"] != initial and cr["check_run_id"] != run["initial_check_run_id"]
    assert cr["dataset_revision_id"] == run["dataset_revision_id"] and cr["initial"] is False
    final_cr = api_a.wait(f"/api/check-runs/{cr['check_run_id']}")
    assert final_cr["status"] == "COMPLETED", final_cr

    assert api_a.get(f"/api/runs/{run_id}/checks").json() == before_doc  # alias never moves to latest
    assert api_a.get(f"/api/reports/{initial}/checks.html").text == before_html
    assert api_a.get(f"/api/runs/{run_id}/summary").json() == before_summary
    new_doc = api_a.get(f"/api/reports/{cr['report_id']}/checks").json()
    assert new_doc["report_id"] == cr["report_id"] and new_doc["run_id"] == run_id
    reports = api_a.get(f"/api/runs/{run_id}/reports").json()
    assert reports["initial_report_id"] == initial
    assert {initial, cr["report_id"]} <= {x["report_id"] for x in reports["items"]}
    rep = api_a.get(f"/api/reports/{cr['report_id']}").json()
    assert rep["status"] == "PUBLISHED" and rep["check_run_id"] == cr["check_run_id"]


def test_report_html_links_to_this_run(api_a, completed_example_run):
    run = completed_example_run["final"]
    html = api_a.get(f"/api/reports/{run['initial_report_id']}/checks.html")
    assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
    assert f"/runs/{run['run_id']}" in html.text
    assert 'href="http' in html.text  # absolute link (FR-010)


def test_report_html_names_report_id(api_a, completed_example_run):
    run = completed_example_run["final"]
    r = api_a.get(f"/api/reports/{run['initial_report_id']}/checks.html")
    assert r.status_code == 200, r.text[:300]
    link_free = r.text.replace(f"/runs/{run['run_id']}/reports/{run['initial_report_id']}", "")
    known_defect(run["initial_report_id"] not in link_free and "Автоматические проверки" in r.text,
                 "DISC-10 (D4 renderer): HTML body names neither report_id nor Run ID; only the link URL carries them")
    assert run["initial_report_id"] in link_free and run["run_id"] in link_free

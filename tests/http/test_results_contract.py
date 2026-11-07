"""Results surface: summary (FR-013), pivot / drill-down (FR-011/012, AC-09/10), params (FR-009), concurrency (NFR-005)."""
from __future__ import annotations

import threading

import pytest

from support.http_api import Api, assert_envelope, known_defect


@pytest.fixture(scope="module")
def events_run(api_a, fixture_root):
    root, _ = fixture_root
    ds = api_a.dataset(root, "dirs", "events/BEFORE", "events/AFTER")
    final = api_a.wait(f"/api/runs/{api_a.start_run(api_a.config(ds['dataset_id'])['config_id']).json()['run_id']}")
    assert final["status"] == "COMPLETED", (final["status"], final["stage"], final["error"])
    return {"run": final, "dataset": ds}


def _summary(api, run_id):
    body = api.get(f"/api/runs/{run_id}/summary").json()
    return body.get("summary", body)


def test_summary_core_metrics(api_a, events_run):
    s = _summary(api_a, events_run["run"]["run_id"])
    assert s["total_apps"] == 6 and s["changed_apps"] == 5 and s["decision_changed_apps"] == 2
    assert s["changed_apps"] <= s["total_apps"]


DIRECTION_KEYS = ("approve_to_reject", "reject_to_approve")


def test_summary_has_decision_directions(api_a, events_run):
    r = api_a.get(f"/api/runs/{events_run['run']['run_id']}/summary")
    assert r.status_code == 200, r.text
    s = r.json().get("summary", r.json())
    flat = {k.lower(): v for k, v in s.items()}
    known_defect(not any(k in flat for k in DIRECTION_KEYS) and "approval_rate_before" in flat,
                 "API-DISC-01: summary has approval rates but no APPROVE->REJECT / REJECT->APPROVE counts (FR-013)")
    assert flat["approve_to_reject"] == 2 and flat["reject_to_approve"] == 0


def test_stage_start_events_reference_code(api_a, events_run):
    items = api_a.get(f"/api/runs/{events_run['run']['run_id']}/events").json()["items"]
    starts = [e for e in items if e["stage"] in ("NORMALIZING", "COMPARING", "AGGREGATING") and e["code_ref"]]
    assert {e["stage"] for e in starts} == {"NORMALIZING", "COMPARING", "AGGREGATING"}
    assert any(e["substep"] == "SEGMENTS" and e["code_ref"] for e in items)  # segments substep of COMPARING
    progress = [e for e in items if e["stage"] == "NORMALIZING" and e["total"]]
    assert progress and progress[-1]["processed"] == progress[-1]["total"] == 6


def test_pivot_cells_carry_locators_and_member_totals(api_a, events_run):
    """FR-011/012, data.md level 2 on the REAL pivot: every cell has dimensions, a positive CNT and an opaque
    group_locator; members of a cell return the FULL distinct total (== CNT) independent of page size; a page
    beyond the end is empty with the same total. Only the documented 501 is a known defect."""
    run_id = events_run["run"]["run_id"]
    r = api_a.post(f"/api/runs/{run_id}/pivot",
                   {"dimensions": ["PATH"], "filters": {"PATH": "characteristics.score_okb"}}, key=None)
    known_defect(r.status_code == 501 and r.json().get("code") == "ANALYTICS_UNAVAILABLE",
                 "API-DISC-02: server pivot rollup not implemented (501 ANALYTICS_UNAVAILABLE); FR-011, AC-10")
    assert r.status_code == 200, r.text[:300]
    cells = r.json()["items"]
    assert len(cells) == 1, cells
    cell = cells[0]
    assert cell["dimensions"] == {"PATH": "characteristics.score_okb"}, cell
    assert isinstance(cell["group_locator"], str) and cell["group_locator"]
    # independent expectation: all 6 applications of the events fixture carry characteristics.score_okb
    assert cell["cnt"] == 6, cell
    url = f"/api/runs/{run_id}/groups/{cell['group_locator']}/applications"
    page = api_a.get(url, params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 6 and len(page["items"]) == 2, page
    everything = api_a.get(url, params={"limit": 50, "offset": 0}).json()
    assert sorted(everything["items"]) == [f"EV0{i}" for i in range(1, 7)] and everything["total"] == 6
    beyond = api_a.get(url, params={"limit": 2, "offset": 10}).json()
    assert beyond["items"] == [] and beyond["total"] == 6, beyond


def test_pivot_rollup_with_user_layout(api_a, events_run):
    # wire format as published by the backend OpenAPI (PivotQuery: dimensions, filters, limit, offset)
    r = api_a.post(f"/api/runs/{events_run['run']['run_id']}/pivot", {"dimensions": ["PATH"], "filters": {}},
                   key=None)
    known_defect(r.status_code == 501 and r.json().get("code") == "ANALYTICS_UNAVAILABLE",
                 "API-DISC-02: server pivot rollup not implemented (501 ANALYTICS_UNAVAILABLE); FR-011, AC-10")
    assert r.status_code == 200, r.text
    body = r.json()
    cells = body.get("cells", body.get("items"))
    assert cells, body
    assert any("characteristics.score_okb" in str(c) for c in cells)


def test_drilldown_returns_full_distinct_total(api_a, events_run):
    r = api_a.post(f"/api/runs/{events_run['run']['run_id']}/pivot-facts/applications",
                   {"group": {"SOURCE": "AFTER", "PATH": "characteristics.score_okb"}, "limit": 1}, key=None)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] and len(body["items"]) == 1
    known_defect("total" in body and body["total"] is None,
                 "API-DISC-02/DISC-03: drill-down page has total=null (no full distinct total); FR-012, AC-09")
    assert body["total"] == 6


def test_drilldown_rejects_unknown_dimension(api_a, events_run):
    r = api_a.post(f"/api/runs/{events_run['run']['run_id']}/pivot-facts/applications",
                   {"group": {"SOURCE": "AFTER", "PATH; DROP TABLE comparison": "x"}}, key=None)
    assert_envelope(r, 422)


def test_application_card(api_a, events_run):
    run_id = events_run["run"]["run_id"]
    card = api_a.get(f"/api/runs/{run_id}/applications/EV03").json()
    new = [r for r in card["comparison"] if r["PATH"] == "characteristics.score_new"]
    assert new and new[0]["CHANGE_TYPE"] == "ATTRIBUTE_NEW" and new[0]["VALUE_BEFORE"] == ""
    assert_envelope(api_a.get(f"/api/runs/{run_id}/applications/NOT_IN_RUN"), 404)


def test_check_params_from_config_are_applied(api_a, events_run):
    ar = [c for c in api_a.builtin_checks() if "ar_drop" in c["name"]][0]
    cfg = api_a.config(events_run["dataset"]["dataset_id"],
                       checks=[{"script_id": ar["script_id"], "params": {"max_drop_rel": 0.99}}])
    final = api_a.wait(f"/api/runs/{api_a.start_run(cfg['config_id']).json()['run_id']}")
    rows = api_a.get(f"/api/runs/{final['run_id']}/checks").json()["checks"]
    assert [(r["ARGUMENT"], r["RESULT"]) for r in rows] == [("KUPI_KUPI", "PASS")]
    default = api_a.get(f"/api/runs/{events_run['run']['run_id']}/checks").json()["checks"]
    assert ("KUPI_KUPI", "FAIL") in [(r["ARGUMENT"], r["RESULT"]) for r in default if "Approval" in r["LABEL"]]


def test_builtin_check_exposes_default_params(api_a):
    found = [c for c in api_a.builtin_checks() if "ar_drop" in c["name"]]
    assert len(found) == 1, found
    known_defect(found[0]["params"] == {},
                 "API-DISC-03: built-in organizer check exposes params={} instead of CHECK.params DEFAULTS (FR-009)")
    assert found[0]["params"].get("max_drop_rel") == 0.10


def test_two_sessions_run_concurrently_without_mixing(base_url, fixture_root):
    root, _ = fixture_root
    results = {}

    def go(name, path):
        api = Api(base_url)
        ds = api.dataset(root, "dirs", f"{path}/BEFORE", f"{path}/AFTER")
        final = api.wait(f"/api/runs/{api.start_run(api.config(ds['dataset_id'])['config_id']).json()['run_id']}")
        results[name] = (final["status"], _summary(api, final["run_id"]))

    threads = [threading.Thread(target=go, args=("A", "events")), threading.Thread(target=go, args=("B", "neutral"))]
    [t.start() for t in threads]
    [t.join(timeout=300) for t in threads]
    assert results["A"][0] == results["B"][0] == "COMPLETED"
    assert (results["A"][1]["total_apps"], results["A"][1]["changed_apps"]) == (6, 5)
    assert (results["B"][1]["total_apps"], results["B"][1]["changed_apps"]) == (3, 0)

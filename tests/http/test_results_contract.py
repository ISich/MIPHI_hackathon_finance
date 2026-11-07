"""Results surface: summary (FR-013), pivot / drill-down (FR-011/012, AC-09/10), params (FR-009), concurrency (NFR-005)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

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
    def go(path):
        api = Api(base_url)
        try:
            ds = api.dataset(root, "dirs", f"{path}/BEFORE", f"{path}/AFTER")
            accepted = api.start_run(api.config(ds["dataset_id"])["config_id"])
            assert accepted.status_code == 202, accepted.text
            final = api.wait(f"/api/runs/{accepted.json()['run_id']}")
            assert final["status"] == "COMPLETED", final
            return final["status"], _summary(api, final["run_id"])
        finally:
            api.http.close()

    # HTTP requests and Api.wait already have bounded deadlines. Waiting on the
    # futures propagates their real errors; a separate 300s join could expire
    # before registration plus Api.wait's own 300s deadline had finished.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {"A": pool.submit(go, "events"), "B": pool.submit(go, "neutral")}
        results = {name: future.result() for name, future in futures.items()}
    assert results["A"][0] == results["B"][0] == "COMPLETED"
    assert (results["A"][1]["total_apps"], results["A"][1]["changed_apps"]) == (6, 5)
    assert (results["B"][1]["total_apps"], results["B"][1]["changed_apps"]) == (3, 0)


@pytest.mark.parametrize("dimensions", [("SOURCE",), ("SOURCE", "CHANGE_TYPE")])
def test_filtered_pivot_matches_application_attributes_and_all_members(api_a, events_run, dimensions):
    """Strict acceptance: overlapping attribute facts must count each application once.

    Reconstruct expected memberships from application cards, independently of pivot
    counts/locators. No analytics-unavailable xfail is permitted in this test.
    """
    from collections import defaultdict

    rid = events_run["run"]["run_id"]
    expected = defaultdict(set)
    for app_id in [f"EV0{i}" for i in range(1, 7)]:
        response = api_a.get(f"/api/runs/{rid}/applications/{app_id}")
        assert response.status_code == 200, response.text[:300]
        card = response.json()
        assert card["run_id"] == rid
        for row in card["comparison"]:
            if row["DIFF_FLAG"] != 1:
                continue
            for source in ("BEFORE", "AFTER"):
                if (source == "BEFORE" and row["CHANGE_TYPE"] == "ATTRIBUTE_NEW") or (
                    source == "AFTER" and row["CHANGE_TYPE"] == "ATTRIBUTE_LOST"
                ):
                    continue
                coordinates = {"SOURCE": source, "CHANGE_TYPE": row["CHANGE_TYPE"]}
                expected[tuple(coordinates[d] for d in dimensions)].add(app_id)
    assert expected, "events fixture must contain changed attributes"

    cells = []
    total = None
    for offset in range(0, len(expected) + 2, 2):
        response = api_a.post(f"/api/runs/{rid}/pivot", {
            "dimensions": list(dimensions), "filters": {"DIFF_FLAG": 1}, "limit": 2, "offset": offset,
        }, key=None)
        assert response.status_code == 200, response.text[:300]
        page = response.json()
        assert page["run_id"] == rid
        assert page["data_revision"] == events_run["run"]["dataset_revision_id"]
        assert page["limit"] == 2 and page["offset"] == offset
        assert page["total"] == len(expected)
        total = page["total"]
        assert len(page["items"]) <= 2
        if offset >= total:
            assert page["items"] == []
        cells.extend(page["items"])
    assert len(cells) == total == len(expected)
    seen = set()
    for cell in cells:
        assert set(cell["dimensions"]) == set(dimensions)
        coordinates = tuple(cell["dimensions"][d] for d in dimensions)
        assert coordinates not in seen
        seen.add(coordinates)
        wanted = sorted(expected[coordinates])
        assert type(cell["cnt"]) is int and cell["cnt"] == len(wanted)
        assert isinstance(cell["group_locator"], str) and cell["group_locator"]
        members = []
        for offset in range(0, len(wanted) + 2, 2):
            response = api_a.get(f"/api/runs/{rid}/groups/{cell['group_locator']}/applications",
                                 params={"limit": 2, "offset": offset})
            assert response.status_code == 200, response.text[:300]
            page = response.json()
            assert page["run_id"] == rid
            assert page["data_revision"] == events_run["run"]["dataset_revision_id"]
            assert page["total"] == len(wanted)
            assert page["limit"] == 2 and page["offset"] == offset
            assert page["items"] == wanted[offset:offset + 2]
            members.extend(page["items"])
        assert members == wanted
    assert seen == set(expected)

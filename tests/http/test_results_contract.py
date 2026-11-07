"""Results surface: summary (FR-013), pivot / drill-down (FR-011/012, AC-09/10), params (FR-009), concurrency (NFR-005)."""
from __future__ import annotations

import threading

import pytest

from support.http_api import Api, assert_envelope


@pytest.fixture(scope="module")
def events_run(api_a, fixture_root):
    root, _ = fixture_root
    ds = api_a.dataset(root, "dirs", "events/BEFORE", "events/AFTER")
    final = api_a.wait(f"/api/runs/{api_a.start_run(api_a.config(ds['dataset_id'])['config_id']).json()['run_id']}")
    assert final["status"] == "COMPLETED", final
    return {"run": final, "dataset": ds}


def _summary(api, run_id):
    body = api.get(f"/api/runs/{run_id}/summary").json()
    return body.get("summary", body)


def test_summary_core_metrics(api_a, events_run):
    s = _summary(api_a, events_run["run"]["run_id"])
    assert s["total_apps"] == 6 and s["changed_apps"] == 5 and s["decision_changed_apps"] == 2
    assert s["changed_apps"] <= s["total_apps"]


@pytest.mark.xfail(reason="API-DISC-01: summary has no decision directions APPROVE->REJECT / REJECT->APPROVE and no "
                          "'changed without decision change' count (FR-013 first screen); only approval rates.")
def test_summary_has_decision_directions(api_a, events_run):
    s = _summary(api_a, events_run["run"]["run_id"])
    text = str(s).upper()
    assert "APPROVE_TO_REJECT" in text or "APPROVE->REJECT" in text or "APPROVE→REJECT" in text


def test_stage_start_events_reference_code(api_a, events_run):
    items = api_a.get(f"/api/runs/{events_run['run']['run_id']}/events").json()["items"]
    starts = [e for e in items if e["stage"] in ("NORMALIZING", "COMPARING", "AGGREGATING") and e["code_ref"]]
    assert {e["stage"] for e in starts} == {"NORMALIZING", "COMPARING", "AGGREGATING"}
    assert any(e["substep"] == "SEGMENTS" and e["code_ref"] for e in items)  # segments substep of COMPARING
    progress = [e for e in items if e["stage"] == "NORMALIZING" and e["total"]]
    assert progress and progress[-1]["processed"] == progress[-1]["total"] == 6


def test_pivot_rollup_is_explicitly_unavailable_not_empty(api_a, events_run):
    r = api_a.post(f"/api/runs/{events_run['run']['run_id']}/pivot", {"rows": ["PATH"]}, key=None)
    if r.status_code == 501:
        assert_envelope(r, 501, "ANALYTICS_UNAVAILABLE")
    else:
        assert r.status_code == 200 and r.json().get("cells") is not None


@pytest.mark.xfail(reason="API-DISC-02 (from DISC-03/04): server pivot rollup with dims/filters and union-membership "
                          "totals is 501; drill-down returns total=null. FR-011/FR-012/AC-09/AC-10 not met yet.")
def test_pivot_rollup_and_drilldown_total(api_a, events_run):
    run_id = events_run["run"]["run_id"]
    assert api_a.post(f"/api/runs/{run_id}/pivot", {"rows": ["PATH"]}, key=None).status_code == 200
    drill = api_a.post(f"/api/runs/{run_id}/pivot-facts/applications",
                       {"group": {"SOURCE": "AFTER", "PATH": "characteristics.score_okb"}, "limit": 1}, key=None)
    assert drill.json()["total"] == 6


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


@pytest.mark.xfail(reason="API-DISC-03: built-in organizer check scripts expose params={} although CHECK.params "
                          "holds DEFAULTS (max_drop_rel, app_ids_limit, ...); UI cannot show/edit defaults (FR-009).")
def test_builtin_check_exposes_default_params(api_a):
    ar = [c for c in api_a.builtin_checks() if "ar_drop" in c["name"]][0]
    assert ar["params"].get("max_drop_rel") == 0.10


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

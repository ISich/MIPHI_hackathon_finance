"""D4 integration (core 421da26): BaseFacts in AGGREGATING, server pivot rollup with signed
group locators (PivotRollup), drill-down totals and pivot-fact totals (ReportService).
Real core, real per-run DuckDB; no test doubles."""
import csv
import io
import json

import pytest

from conftest import BACKEND_DIR, peer, wait_run
from helpers import config, copy_pair_dirs, start_run


@pytest.fixture
def finished(client, env):
    root = copy_pair_dirs(env["core"], env["data"], n=3)
    # T0002: AFTER identical to BEFORE -> no change for that application
    (root / "AFTER" / "T0002.json").write_bytes((root / "BEFORE" / "T0002.json").read_bytes())
    ds = client.post("/api/datasets", json={"name": "d4", "root": "data", "mode": "dirs",
                                            "before": "set1/BEFORE", "after": "set1/AFTER"}).json()
    done = wait_run(client, start_run(client, config(client, ds["dataset_id"], checks=[])["config_id"]).json()["run_id"])
    assert done["status"] == "COMPLETED", done
    return done


def _segments(client, run_id):
    arts = {a["kind"]: a for a in client.get(f"/api/runs/{run_id}/artifacts").json()["items"]}
    text = client.get(arts["segments"]["download"]).content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def test_core_pin_is_421da26(client):
    assert (BACKEND_DIR / "CORE_COMMIT").read_text().strip().startswith("421da26")
    core = {c["name"]: c for c in client.get("/ready").json()["checks"]}["core_package"]
    assert core["ok"] and core["details"]["commit"].startswith("421da26")


def test_base_facts_are_materialized_during_aggregating(client, finished):
    summary = client.get(f"/api/runs/{finished['run_id']}/summary").json()
    assert summary["mart_tables"]["base_facts"] > 0 and summary["mart_tables"]["base_membership"] > 0
    assert summary["membership_validation"]["ok"] is True


def test_pivot_rollup_cells_and_member_drilldown(client, finished):
    rid = finished["run_id"]
    segs = _segments(client, rid)
    expected = {}
    for s in segs:
        expected[str(s["DECISION_CHANGED"])] = expected.get(str(s["DECISION_CHANGED"]), 0) + 1
    r = client.post(f"/api/runs/{rid}/pivot", json={"dimensions": ["DECISION_CHANGED"], "limit": 50})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["run_id"] == rid and body["data_revision"] == finished["dataset_revision_id"]
    got = {str(i["dimensions"]["DECISION_CHANGED"]): i["cnt"] for i in body["items"]}
    assert got == expected == {"0": 1, "1": 2}
    assert body["total"] == 2
    cell = next(i for i in body["items"] if str(i["dimensions"]["DECISION_CHANGED"]) == "1")
    members = client.get(f"/api/runs/{rid}/groups/{cell['group_locator']}/applications?limit=1&offset=1").json()
    assert members["total"] == 2 and members["items"] == ["T0001"]  # page of 1, full distinct total
    # filters + distinct (not summed) totals over many attribute facts per application
    r = client.post(f"/api/runs/{rid}/pivot", json={"dimensions": ["SOURCE"], "filters": {"CHANGE_TYPE": ["VALUE_CHANGED", "ATTRIBUTE_NEW"]}})
    assert {i["dimensions"]["SOURCE"]: i["cnt"] for i in r.json()["items"]} == {"AFTER": 2, "BEFORE": 2}


def test_pivot_rejects_unknown_dimension_bad_paging_and_foreign_or_forged_locators(client, finished):
    rid = finished["run_id"]
    for body in ({"dimensions": ["APP_ID; DROP"]}, {"dimensions": []}, {"dimensions": ["PATH"], "limit": 501},
                 {"dimensions": ["PATH"], "filters": {"nope": 1}}):
        r = client.post(f"/api/runs/{rid}/pivot", json=body)
        assert r.status_code == 422 and r.json()["code"] == "PIVOT_QUERY_INVALID", body
    loc = client.post(f"/api/runs/{rid}/pivot", json={"dimensions": ["SOURCE"]}).json()["items"][0]["group_locator"]
    forged = loc[:-3] + ("AAA" if not loc.endswith("AAA") else "BBB")
    r = client.get(f"/api/runs/{rid}/groups/{forged}/applications")
    assert r.status_code == 422 and r.json()["code"] == "PIVOT_QUERY_INVALID"
    # same owner, other run: the locator is bound to its run/revision
    other = wait_run(client, start_run(client, config(client, finished["dataset_id"], checks=[])["config_id"]).json()["run_id"])
    r = client.get(f"/api/runs/{other['run_id']}/groups/{loc}/applications")
    assert r.status_code == 422
    # other owner: run not visible at all
    stranger = peer(client.app)
    assert stranger.post(f"/api/runs/{rid}/pivot", json={"dimensions": ["SOURCE"]}).status_code == 404
    assert stranger.get(f"/api/runs/{rid}/groups/{loc}/applications").status_code == 404


def test_report_service_totals_for_drilldown_and_pivot_facts(client, finished):
    rid = finished["run_id"]
    d = client.post(f"/api/runs/{rid}/pivot-facts/applications",
                    json={"group": {"SOURCE": "AFTER", "PATH": "decisionResult.decision"}, "limit": 1}).json()
    assert d["total"] == 3 and len(d["items"]) == 1
    pf = client.get(f"/api/runs/{rid}/pivot-facts?limit=5").json()
    assert isinstance(pf["total"], int) and pf["total"] >= 5 and len(pf["items"]) == 5
    assert client.get(f"/api/runs/{rid}/pivot-facts?limit=501").status_code == 422


def test_pivot_not_ready_for_unfinished_run(no_worker_client):
    from helpers import demo_dataset
    c = no_worker_client
    run = start_run(c, config(c, demo_dataset(c)["dataset_id"], checks=[])["config_id"]).json()
    r = c.post(f"/api/runs/{run['run_id']}/pivot", json={"dimensions": ["SOURCE"]})
    assert r.status_code == 409 and r.json()["code"] == "NOT_READY"

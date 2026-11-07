"""Owner isolation of two sessions (FR-016, NFR-005, AC-17, api.md 'Owner scope на каждом route')."""
from __future__ import annotations

import pytest

from support.http_api import assert_envelope


@pytest.fixture(scope="module")
def a_entities(api_a, completed_example_run):
    run = completed_example_run["final"]
    script = api_a.script("check", "def run(mart, params=None):\n    return []\n")
    assert script.status_code == 201, script.text
    return {"run": run, "config": completed_example_run["config"], "dataset": completed_example_run["dataset"],
            "script": script.json()}


def _foreign_urls(e):
    run_id, rep = e["run"]["run_id"], e["run"]["initial_report_id"]
    cr = e["run"]["initial_check_run_id"]
    return [
        f"/api/runs/{run_id}", f"/api/runs/{run_id}/events", f"/api/runs/{run_id}/code/normalize",
        f"/api/runs/{run_id}/summary", f"/api/runs/{run_id}/artifacts", f"/api/runs/{run_id}/checks",
        f"/api/runs/{run_id}/reports", f"/api/runs/{run_id}/pivot-facts",
        f"/api/runs/{run_id}/applications/I32554354", f"/api/check-runs/{cr}",
        f"/api/reports/{rep}", f"/api/reports/{rep}/checks", f"/api/reports/{rep}/checks.html",
        f"/api/configurations/{e['config']['config_id']}", f"/api/scripts/{e['script']['script_id']}",
        f"/api/datasets/{e['dataset']['dataset_id']}",
    ]


def test_sessions_are_distinct(api_a, api_b):
    api_a.session(), api_b.session()
    assert api_a.http.cookies.get("dd_session") != api_b.http.cookies.get("dd_session")


def test_foreign_ids_are_hidden_as_not_found(api_a, api_b, a_entities):
    for url in _foreign_urls(a_entities):
        assert api_a.get(url).status_code == 200, url
        fake = url.replace(a_entities["run"]["run_id"], "run_doesnotexist")
        r = api_b.get(url)
        assert r.status_code == 404, (url, r.status_code, r.text[:200])
        if url != fake:  # same answer as a nonexistent id: existence is not leaked
            assert api_b.get(fake).status_code == 404


def test_foreign_entities_not_listed(api_a, api_b, a_entities):
    runs_b = api_b.get("/api/runs", params={"limit": 200}).json()
    assert a_entities["run"]["run_id"] not in {r["run_id"] for r in runs_b["items"]}
    assert a_entities["config"]["config_id"] not in {c["config_id"] for c in api_b.get("/api/configurations").json()}
    assert a_entities["script"]["script_id"] not in {s["script_id"] for s in api_b.get("/api/scripts").json()}
    assert a_entities["dataset"]["dataset_id"] not in {d["dataset_id"] for d in api_b.get("/api/datasets").json()}


def test_foreign_config_cannot_be_run_or_mutated(api_a, api_b, a_entities):
    assert_envelope(api_b.start_run(a_entities["config"]["config_id"]), 404)
    sid = a_entities["script"]["script_id"]
    assert_envelope(api_b.put(f"/api/scripts/{sid}", {"code": "x = 1\n"}), 404)
    assert_envelope(api_b.post(f"/api/runs/{a_entities['run']['run_id']}/check-runs", {"checks": []}), 404)
    assert api_a.get(f"/api/scripts/{sid}").json()["revision"] == a_entities["script"]["revision"]


def test_foreign_script_cannot_be_referenced_in_own_config(api_b, a_entities, examples_root):
    ds = api_b.dataset(examples_root, "files", "I32554354_other.json", "I32554354.json")
    r = api_b.post("/api/configurations", {"name": "steal", "dataset_id": ds["dataset_id"],
                                           "checks": [{"script_id": a_entities["script"]["script_id"]}]}, key=None)
    assert_envelope(r, (404, 422))


OWNER_HEADERS = ("x-owner-id", "x-user-id", "x-forwarded-user", "x-remote-user", "owner-id")


@pytest.mark.parametrize("header", OWNER_HEADERS)
def test_owner_header_is_ignored(base_url, header):
    """CR #4: A creates an entity while sending a chosen owner header; B sends the SAME header value.
    If the backend derived the owner from that header, B would be A. B must get 404 and not see it."""
    import uuid

    from support.http_api import Api

    forged = f"qa-owner-{uuid.uuid4().hex}"
    a, b = Api(base_url), Api(base_url)
    try:
        a.session(), b.session()
        created = a.http.post("/api/scripts", headers={header: forged},
                              json={"kind": "check", "name": "hdr", "code": "x = 1\n", "params": {}})
        assert created.status_code == 201, created.text
        sid = created.json()["script_id"]
        assert a.get(f"/api/scripts/{sid}", headers={header: forged}).status_code == 200
        r = b.get(f"/api/scripts/{sid}", headers={header: forged})
        assert r.status_code == 404, (header, r.status_code)
        listed = b.get("/api/scripts", headers={header: forged}).json()
        assert sid not in {x["script_id"] for x in listed}
    finally:
        a.http.close()
        b.http.close()


def test_owner_in_body_is_rejected(api_b, a_entities):
    body = {"configuration_id": a_entities["config"]["config_id"], "owner_id": "x"}
    assert_envelope(api_b.post("/api/runs", body), 422)


def test_foreign_dataset_cannot_be_referenced(api_b, a_entities):
    """CR #5: B must not be able to configure (and thus run) A's dataset."""
    r = api_b.post("/api/configurations", {"name": "steal-ds", "dataset_id": a_entities["dataset"]["dataset_id"]},
                   key=None)
    assert_envelope(r, (404, 422))


@pytest.mark.parametrize("slot", ["normalize", "compare", "segments", "aggregate"])
def test_foreign_procedure_cannot_be_referenced_in_slot(api_a, api_b, examples_root, slot):
    """CR #5: a foreign procedure script in a slot of B's configuration is refused."""
    kinds = {k["kind"]: k for k in api_a.get("/api/script-kinds").json()}
    foreign = api_a.script(slot, kinds[slot]["example"])
    assert foreign.status_code == 201, foreign.text
    ds = api_b.dataset(examples_root, "files", "I32554354_other.json", "I32554354.json")
    r = api_b.post("/api/configurations", {"name": "steal-slot", "dataset_id": ds["dataset_id"],
                                           "slots": {slot: {"script_id": foreign.json()["script_id"]}}}, key=None)
    assert_envelope(r, (404, 422))


def test_foreign_check_cannot_be_used_in_own_check_run(api_b, a_entities, examples_root):
    """CR #5: B's check-only run on B's own Run may not reference A's check script."""
    ds = api_b.dataset(examples_root, "files", "I32554354_other.json", "I32554354.json")
    run = api_b.wait(f"/api/runs/{api_b.start_run(api_b.config(ds['dataset_id'])['config_id']).json()['run_id']}")
    assert run["status"] == "COMPLETED", run
    r = api_b.post(f"/api/runs/{run['run_id']}/check-runs", {"checks": [{"script_id": a_entities["script"]["script_id"]}]})
    assert_envelope(r, (404, 422))


def test_forged_cookie_gets_fresh_owner(base_url, a_entities):
    import httpx

    with httpx.Client(base_url=base_url, cookies={"dd_session": "forged-token"}) as c:
        assert c.get(f"/api/runs/{a_entities['run']['run_id']}").status_code == 404


def _locator_from_pivot(body):
    """Find an opaque group locator in a pivot response (field name not frozen yet)."""
    cells = body.get("cells", body.get("items", [])) if isinstance(body, dict) else []
    for cell in cells:
        for key in ("group", "locator", "group_locator", "group_id"):
            if isinstance(cell, dict) and isinstance(cell.get(key), str) and cell[key]:
                return cell[key]
    return None


def test_query_endpoints_and_group_locators_are_owner_scoped(api_a, api_b, completed_example_run):
    """CR2 #4: pivot, pivot-facts, drill-down and groups/{locator}/applications exercised as A (control) and as B.
    B must get 404 and none of A's APP_IDs, even with a real locator obtained by A."""
    run_id = completed_example_run["final"]["run_id"]
    app = "I32554354"
    pivot_body = {"dimensions": ["PATH"], "filters": {}}
    drill_body = {"group": {"SOURCE": "AFTER", "PATH": "decisionResult.decision"}}

    a_pivot = api_a.post(f"/api/runs/{run_id}/pivot", pivot_body, key=None)
    assert a_pivot.status_code == 200 or (a_pivot.status_code == 501 and
                                          a_pivot.json().get("code") == "ANALYTICS_UNAVAILABLE"), a_pivot.text[:300]
    a_drill = api_a.post(f"/api/runs/{run_id}/pivot-facts/applications", drill_body, key=None)
    assert a_drill.status_code == 200 and app in a_drill.text, a_drill.text[:300]
    assert api_a.get(f"/api/runs/{run_id}/pivot-facts").status_code == 200
    locator = _locator_from_pivot(a_pivot.json()) if a_pivot.status_code == 200 else None
    if locator:
        a_group = api_a.get(f"/api/runs/{run_id}/groups/{locator}/applications")
        assert a_group.status_code == 200 and app in a_group.text, a_group.text[:300]
    group_url = f"/api/runs/{run_id}/groups/{locator or 'qa-no-locator-available'}/applications"

    for resp in (api_b.post(f"/api/runs/{run_id}/pivot", pivot_body, key=None),
                 api_b.post(f"/api/runs/{run_id}/pivot-facts/applications", drill_body, key=None),
                 api_b.get(f"/api/runs/{run_id}/pivot-facts"),
                 api_b.get(group_url)):
        assert resp.status_code == 404, (resp.request.url, resp.status_code, resp.text[:200])
        assert app not in resp.text

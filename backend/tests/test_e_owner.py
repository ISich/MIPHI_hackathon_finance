"""Slice E: anonymous server-side sessions and owner scope on every route."""
from fastapi.testclient import TestClient

from conftest import wait_run
from helpers import config, demo_dataset, idem, start_run


def test_session_cookie_is_httponly_samesite_and_random(client):
    r = client.get("/api/session")
    cookie = r.headers["set-cookie"]
    assert "dd_session=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert "Secure" not in cookie  # local HTTP mode (DD_COOKIE_SECURE=0) is explicit
    other = TestClient(client.app)
    c2 = other.get("/api/session").headers["set-cookie"]
    assert c2.split(";")[0] != cookie.split(";")[0]
    assert len(cookie.split(";")[0].split("=", 1)[1]) >= 40
    # no new cookie once a valid session exists
    assert "set-cookie" not in client.get("/api/session").headers


def test_forged_cookie_and_owner_header_grant_nothing(client):
    ds = demo_dataset(client)
    cfg = config(client, ds["dataset_id"], checks=[])
    stranger = TestClient(client.app, cookies={"dd_session": "forged-token"})
    r = stranger.get(f"/api/configurations/{cfg['config_id']}", headers={"x-owner-id": "anything"})
    assert r.status_code == 404
    issued = r.headers["set-cookie"].split(";")[0]
    assert issued.startswith("dd_session=") and issued != "dd_session=forged-token"  # fresh session issued


def test_two_sessions_cannot_read_each_others_entities(client, env):
    a = client
    b = TestClient(a.app)
    ds = demo_dataset(a)
    script = a.post("/api/scripts", json={"kind": "check", "name": "mine", "code": "CHECK = {}\n"}).json()
    cfg = config(a, ds["dataset_id"])
    run = start_run(a, cfg["config_id"]).json()
    done = wait_run(a, run["run_id"])
    assert done["status"] == "COMPLETED"
    rid, rep = run["run_id"], done["initial_report_id"]
    art = a.get(f"/api/runs/{rid}/artifacts").json()["items"][0]
    cr = done["initial_check_run_id"]
    forbidden = [
        f"/api/datasets/{ds['dataset_id']}", f"/api/scripts/{script['script_id']}",
        f"/api/configurations/{cfg['config_id']}", f"/api/runs/{rid}", f"/api/runs/{rid}/events",
        f"/api/runs/{rid}/code/normalize", f"/api/runs/{rid}/code/check-01", f"/api/runs/{rid}/summary",
        f"/api/runs/{rid}/artifacts", f"/api/runs/{rid}/artifacts/{art['artifact_id']}",
        f"/api/runs/{rid}/pivot-facts", f"/api/runs/{rid}/applications/I32554354", f"/api/runs/{rid}/checks",
        f"/api/runs/{rid}/reports", f"/api/check-runs/{cr}", f"/api/check-runs/{cr}/code/check-01",
        f"/api/reports/{rep}", f"/api/reports/{rep}/checks", f"/api/reports/{rep}/checks.html",
    ]
    for url in forbidden:
        assert a.get(url).status_code == 200, url
        r = b.get(url)
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND", url
    # mutations / nested references
    assert b.put(f"/api/scripts/{script['script_id']}", json={"code": "x=1\n"}).status_code == 404
    assert b.post("/api/runs", json={"configuration_id": cfg["config_id"]}, headers=idem()).status_code == 404
    assert b.post(f"/api/runs/{rid}/check-runs", json={"checks": []}, headers=idem()).status_code == 404
    assert b.post(f"/api/runs/{rid}/pivot-facts/applications",
                  json={"group": {"SOURCE": "AFTER"}}).status_code == 404
    assert b.post("/api/configurations", json={"name": "x", "dataset_id": ds["dataset_id"]}).status_code == 404
    own_ds = demo_dataset(b)
    r = b.post("/api/configurations", json={"name": "x", "dataset_id": own_ds["dataset_id"],
                                            "checks": [{"script_id": script["script_id"]}]})
    assert r.status_code == 404
    b_run_cfg = config(b, own_ds["dataset_id"], checks=[])
    b_run = wait_run(b, start_run(b, b_run_cfg["config_id"]).json()["run_id"])
    r = b.post(f"/api/runs/{b_run['run_id']}/check-runs", json={"checks": [{"script_id": script["script_id"]}]},
               headers=idem())
    assert r.status_code == 404
    # listings are scoped
    assert [x["run_id"] for x in b.get("/api/runs").json()["items"]] == [b_run["run_id"]]
    assert all(s["shared"] or s["script_id"] != script["script_id"] for s in b.get("/api/scripts").json())
    assert ds["dataset_id"] not in [d["dataset_id"] for d in b.get("/api/datasets").json()]
    assert [c["config_id"] for c in b.get("/api/configurations").json()] == [b_run_cfg["config_id"]]


def test_idempotency_keys_are_scoped_per_owner(client):
    a, b = client, TestClient(client.app)
    key = {"Idempotency-Key": "same-key"}
    ra = start_run(a, config(a, demo_dataset(a)["dataset_id"], checks=[])["config_id"], key).json()
    rb = start_run(b, config(b, demo_dataset(b)["dataset_id"], checks=[])["config_id"], key).json()
    assert ra["run_id"] != rb["run_id"]
    wait_run(a, ra["run_id"]), wait_run(b, rb["run_id"])

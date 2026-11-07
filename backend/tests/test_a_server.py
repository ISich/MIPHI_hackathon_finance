"""Slice A: live server, wire contract, error envelope, readiness."""
from openapi_spec_validator import validate


def test_health_is_alive(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.headers.get("x-request-id")


def test_ready_reports_real_dependencies(client):
    r = client.get("/ready")
    body = r.json()
    assert r.status_code == 200, body
    assert body["ready"] is True
    names = {c["name"]: c for c in body["checks"]}
    for required in ("database", "core_package", "duckdb", "checks_dir", "data_roots", "worker"):
        assert names[required]["ok"] is True, names[required]
    assert names["core_package"]["details"]["commit"]
    assert body["execution_mode"] == "builtin-only"


def test_ready_is_false_when_checks_dir_missing(env, monkeypatch, tmp_path):
    from conftest import make_client
    monkeypatch.setenv("DD_CHECKS_DIR", str(tmp_path / "nope"))
    with make_client() as c:
        r = c.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False
    assert {c["name"]: c["ok"] for c in body["checks"]}["checks_dir"] is False


def test_openapi_is_valid(client):
    spec = client.get("/openapi.json").json()
    validate(spec)
    assert "/api/runs" in spec["paths"]


def test_error_envelope_for_unknown_route(client):
    r = client.get("/api/runs/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert set(body) == {"code", "message", "details", "request_id"}
    assert body["code"] == "NOT_FOUND"
    assert body["request_id"] == r.headers["x-request-id"]


def test_validation_error_envelope(client):
    r = client.post("/api/runs", content="{not json", headers={"content-type": "application/json", "Idempotency-Key": "k1"})
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"

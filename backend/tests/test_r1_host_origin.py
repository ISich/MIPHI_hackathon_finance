"""Review #1 (BLOCKER): DNS rebinding / cross-origin protection, not only CLI bind address."""
import pytest

from conftest import make_client, peer
from helpers import demo_dataset


def test_foreign_host_header_is_rejected_before_any_session(client):
    r = client.get("/api/datasets", headers={"host": "attacker.example"})
    assert r.status_code == 400 and r.json()["code"] == "HOST_NOT_ALLOWED"
    assert "set-cookie" not in r.headers
    assert client.get("/health", headers={"host": "rebind.attacker.example:8000"}).status_code == 400
    assert client.get("/api/datasets", headers={"host": "127.0.0.1:8000"}).status_code == 200
    assert client.get("/api/datasets", headers={"host": "localhost:8000"}).status_code == 200


def test_cross_origin_state_changing_request_is_rejected(client):
    ds = demo_dataset(client)
    body = {"name": "x", "dataset_id": ds["dataset_id"], "checks": []}
    r = client.post("/api/configurations", json=body, headers={"origin": "http://evil.example"})
    assert r.status_code == 403 and r.json()["code"] == "ORIGIN_NOT_ALLOWED"
    r = client.post("/api/configurations", json=body, headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    # same-origin is fine; non-browser clients send no Origin (cross-origin, incl. :5173, is covered in test_rr4)
    assert client.post("/api/configurations", json=body, headers={"origin": "http://127.0.0.1"}).status_code == 201
    assert client.post("/api/configurations", json=body).status_code == 201


def test_trusted_local_refuses_non_loopback_peers_even_without_cli(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    with make_client() as c:
        assert c.get("/api/script-kinds").status_code == 200
        remote = peer(c.app, client=("10.0.0.5", 40000))
        r = remote.get("/api/script-kinds")
        assert r.status_code == 403 and r.json()["code"] == "REMOTE_CLIENT_NOT_ALLOWED"


def test_trusted_local_refuses_non_loopback_allowed_hosts(env, monkeypatch):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_ALLOWED_HOSTS", "127.0.0.1,finance.example.org")
    from dd_backend.settings import SettingsError
    with pytest.raises(SettingsError):
        make_client()

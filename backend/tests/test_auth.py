"""Account ownership, password storage, session rotation, and login failures."""
from datetime import datetime, timedelta, timezone

from conftest import make_client, peer
from dd_backend import auth, sessions


def login(client, username="admin", password="admin12345"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_login_rotates_cookie_and_logout_revokes_it(no_worker_client):
    c = no_worker_client
    initial = c.get("/api/session")
    assert initial.json()["authenticated"] is False
    assert initial.json()["user"] is None
    anonymous = c.cookies.get("dd_session")
    response = login(c)
    assert response.status_code == 200
    assert response.json()["user"] == {"username": "admin", "display_name": "Аналитик"}
    assert response.json()["authenticated"] is True
    assert response.headers["cache-control"] == "no-store"
    assert "HttpOnly" in response.headers["set-cookie"]
    token = c.cookies.get("dd_session")
    assert token != anonymous
    assert sessions.resolve(c.app.state.db, anonymous) is None
    assert c.get("/api/session").json()["authenticated"] is True
    assert c.post("/api/auth/logout").json()["authenticated"] is False
    assert sessions.resolve(c.app.state.db, token) is None
    assert peer(c.app, cookies={"dd_session": token}).get("/api/session").json()["authenticated"] is False


def test_login_without_bootstrap_sets_account_cookie(no_worker_client):
    c = no_worker_client
    assert login(c).json()["authenticated"] is True
    assert c.get("/api/session").json()["authenticated"] is True
    assert c.app.state.db.one("SELECT COUNT(*) AS n FROM sessions")["n"] == 1


def test_saved_work_survives_logout_and_another_browser(no_worker_client):
    a = no_worker_client
    assert login(a).status_code == 200
    script = a.post("/api/scripts", json={"kind": "check", "name": "account work", "code": "CHECK = {}\n"}).json()
    path = f"/api/scripts/{script['script_id']}"
    stranger = peer(a.app)
    assert stranger.get(path).status_code == 404
    b = peer(a.app)
    assert login(b).status_code == 200
    assert b.get(path).status_code == 200
    a.post("/api/auth/logout")
    assert a.get(path).status_code == 404
    assert b.get(path).status_code == 200  # logout affects only this browser
    assert login(a).status_code == 200
    assert a.get(path).json()["name"] == "account work"


def test_wrong_credentials_do_not_authenticate_or_leak_password(no_worker_client):
    c = no_worker_client
    for username, password in [("admin", "wrong-password"), ("unknown", "admin12345")]:
        r = login(c, username, password)
        assert r.status_code == 401
        assert r.json()["code"] == "INVALID_CREDENTIALS"
        assert password not in r.text
        assert c.get("/api/session").json()["authenticated"] is False
    invalid = login(c, "admin", "x" * 257)
    assert invalid.status_code == 422
    assert "x" * 257 not in invalid.text
    stored = c.app.state.db.one("SELECT password_hash FROM users")["password_hash"]
    assert "admin12345" not in stored
    assert auth.verify("admin12345", stored)


def test_login_is_limited_and_recovers_after_window(no_worker_client):
    c = no_worker_client
    for _ in range(10):
        assert login(c, password="wrong-password").status_code == 401
    assert login(c).status_code == 429
    with c.app.state.db.tx() as con:
        con.execute("UPDATE login_limits SET started_at = started_at - 61")
    assert login(c).status_code == 200


def test_cookie_expires_server_side(no_worker_client):
    c = no_worker_client
    login(c)
    expired = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    with c.app.state.db.tx() as con:
        con.execute("UPDATE sessions SET created_at = ?", (expired,))
    assert c.get("/api/session").json()["authenticated"] is False


def test_password_change_preserves_owner_and_revokes_sessions(no_worker_client, monkeypatch):
    c = no_worker_client
    login(c)
    db = c.app.state.db
    token = c.cookies.get("dd_session")
    owner = sessions.resolve(db, token)
    monkeypatch.setenv("DD_AUTH_PASSWORD", "new-private-password")
    auth.configure(db, c.app.state.settings.allowed_hosts)
    assert sessions.resolve(db, token) is None
    assert login(c).status_code == 401
    assert login(c, password="new-private-password").status_code == 200
    assert sessions.resolve(db, c.cookies.get("dd_session")) == owner


def test_account_survives_app_restart(no_worker_client):
    c = no_worker_client
    login(c)
    token = c.cookies.get("dd_session")
    owner = sessions.resolve(c.app.state.db, token)
    with make_client() as restarted:
        restarted.cookies.set("dd_session", token)
        assert restarted.get("/api/session").json()["authenticated"] is True
        assert sessions.resolve(restarted.app.state.db, token) == owner


def test_login_rejects_cross_origin(no_worker_client):
    c = no_worker_client
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin12345"},
               headers={"origin": "https://untrusted.example"})
    assert r.status_code == 403
    assert r.json()["code"] == "ORIGIN_NOT_ALLOWED"


def test_public_host_requires_private_password(env, monkeypatch):
    import pytest
    from dd_backend.settings import SettingsError
    monkeypatch.setenv("DD_ALLOWED_HOSTS", "127.0.0.1,finance.example")
    with pytest.raises(SettingsError, match="DD_AUTH_PASSWORD"):
        make_client()

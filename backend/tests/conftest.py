from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
CORE_SHA = (BACKEND_DIR / "CORE_COMMIT").read_text().strip()
CORE_DIR = BACKEND_DIR / ".core" / CORE_SHA


def core_assets() -> Path:
    if not (CORE_DIR / ".complete").exists():
        pytest.fail("Core assets missing: run backend/scripts/fetch_core.sh first")
    return CORE_DIR


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated backend home with allowlisted roots: core examples + a tmp data root."""
    core = core_assets()
    data = tmp_path / "data"
    data.mkdir()
    home = tmp_path / "home"
    monkeypatch.setenv("DD_HOME", str(home))
    monkeypatch.setenv("DD_DATA_ROOTS", f"examples={core / 'examples'},data={data}")
    monkeypatch.setenv("DD_CHECKS_DIR", str(core / "checks"))
    monkeypatch.setenv("DD_EXECUTION_MODE", "builtin-only")
    monkeypatch.setenv("DD_EMBEDDED_WORKER", "1")
    monkeypatch.setenv("DD_RUN_TIMEOUT_SECONDS", "120")
    return {"home": home, "data": data, "core": core}


LOOPBACK = {"base_url": "http://127.0.0.1", "client": ("127.0.0.1", 50000)}


def make_client(**kwargs) -> TestClient:
    from dd_backend.app import create_app
    return TestClient(create_app(), **{**LOOPBACK, **kwargs})


def peer(app, **kwargs) -> TestClient:
    """Another browser session against the same app (no lifespan => no second worker)."""
    return TestClient(app, **{**LOOPBACK, **kwargs})


@pytest.fixture
def client(env):
    with make_client() as c:
        yield c


def wait_run(client: TestClient, run_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] in ("COMPLETED", "FAILED"):
            return body
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not finish: {body}")


def wait_check_run(client: TestClient, check_run_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/check-runs/{check_run_id}").json()
        if body["status"] in ("COMPLETED", "FAILED"):
            return body
        time.sleep(0.1)
    raise AssertionError(f"check run {check_run_id} did not finish: {body}")

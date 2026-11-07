"""Black-box HTTP fixtures. The server is NOT started here and the core is NOT mocked.

Environment:
  QA_BASE_URL       e.g. http://127.0.0.1:18765 (loopback only; required, else tests skip)
  QA_FIXTURE_ROOT   server data-root name that points at QA_FIXTURE_DIR (optional)
  QA_FIXTURE_DIR    local dir produced by scripts/make_http_fixtures.py (optional)
  QA_EXAMPLES_ROOT  server data-root name with the core examples (default: examples)
  QA_RUN_TIMEOUT    seconds to wait for a Run (default 300)
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from support.http_api import Api

BASE_URL = os.environ.get("QA_BASE_URL", "")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "/http/" in str(item.fspath):
            item.add_marker(pytest.mark.http)


@pytest.fixture(scope="session")
def base_url() -> str:
    if not BASE_URL:
        pytest.skip("QA_BASE_URL not set: black-box HTTP tests need a running backend (NOT VERIFIED)")
    host = urlsplit(BASE_URL).hostname
    if host not in ("127.0.0.1", "localhost", "::1"):
        pytest.exit(f"QA_BASE_URL must be loopback, got {host!r}", returncode=2)
    return BASE_URL.rstrip("/")


@pytest.fixture(scope="session")
def api_a(base_url):
    a = Api(base_url)
    yield a
    a.http.close()


@pytest.fixture(scope="session")
def api_b(base_url):
    b = Api(base_url)
    yield b
    b.http.close()


@pytest.fixture(scope="session")
def examples_root() -> str:
    return os.environ.get("QA_EXAMPLES_ROOT", "examples")


@pytest.fixture(scope="session")
def fixture_root() -> tuple[str, Path]:
    name, folder = os.environ.get("QA_FIXTURE_ROOT"), os.environ.get("QA_FIXTURE_DIR")
    if not (name and folder):
        pytest.skip("QA_FIXTURE_ROOT/QA_FIXTURE_DIR not set (synthetic datasets unavailable) - NOT VERIFIED")
    return name, Path(folder)


SUPPORTED_MODES = ("builtin-only", "trusted-local")


@pytest.fixture(scope="session")
def execution_mode(api_a) -> str:
    """CR3 #2: mode-dependent skips are only allowed for a mode the server explicitly reports from the enum;
    otherwise both sides of the execution policy would be skipped silently."""
    reported = api_a.session().get("execution_mode")
    if reported not in SUPPORTED_MODES:
        pytest.fail(f"/api/session execution_mode={reported!r} is not one of {SUPPORTED_MODES}; "
                    "execution-policy coverage cannot be selected", pytrace=False)
    return reported


@pytest.fixture(scope="session", autouse=True)
def _expected_execution_mode(request):
    """CR #2: if the runner declares the mode it launched, the server must report exactly that mode."""
    expected = os.environ.get("QA_EXECUTION_MODE")
    if not expected or not BASE_URL:
        return
    api = request.getfixturevalue("api_a")
    reported = api.session().get("execution_mode")
    if reported != expected:
        pytest.fail(f"execution_mode mismatch: server reports {reported!r}, QA_EXECUTION_MODE={expected!r}",
                    pytrace=False)


@pytest.fixture(scope="session")
def completed_example_run(api_a, examples_root):
    """One real Run on the core example pair, all built-in checks; shared by several tests."""
    ds = api_a.dataset(examples_root, "files", "I32554354_other.json", "I32554354.json")
    cfg = api_a.config(ds["dataset_id"])
    started = time.monotonic()
    r = api_a.start_run(cfg["config_id"])
    accept_seconds = time.monotonic() - started
    assert r.status_code == 202, r.text
    run = r.json()
    final = api_a.wait(f"/api/runs/{run['run_id']}")
    return {"dataset": ds, "config": cfg, "accepted": run, "accept_seconds": accept_seconds,
            "location": r.headers.get("location"), "final": final}

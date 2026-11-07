"""health / ready / openapi / error envelope (api.md §ресурсы, §ошибки)."""
from __future__ import annotations

import pytest

from support.http_api import assert_envelope

# Every route of docs/contracts/api.md (method, OpenAPI path template).
API_MD_ROUTES = [
    ("get", "/api/datasets"), ("post", "/api/datasets"),
    ("get", "/api/scripts"), ("post", "/api/scripts"), ("get", "/api/script-kinds"),
    ("get", "/api/scripts/{script_id}"),
    ("get", "/api/configurations"), ("post", "/api/configurations"), ("get", "/api/configurations/{config_id}"),
    ("post", "/api/runs"), ("get", "/api/runs"), ("get", "/api/runs/{run_id}"),
    ("get", "/api/runs/{run_id}/events"), ("get", "/api/runs/{run_id}/code/{slot}"),
    ("get", "/api/runs/{run_id}/summary"), ("post", "/api/runs/{run_id}/pivot"),
    ("get", "/api/runs/{run_id}/groups/{group}/applications"),
    ("get", "/api/runs/{run_id}/applications/{app_id}"),
    ("get", "/api/runs/{run_id}/checks"), ("get", "/api/runs/{run_id}/reports"),
    ("post", "/api/runs/{run_id}/check-runs"), ("get", "/api/check-runs/{check_run_id}"),
    ("get", "/api/reports/{report_id}"), ("get", "/api/reports/{report_id}/checks"),
    ("get", "/api/reports/{report_id}/checks.html"),
    ("get", "/health"), ("get", "/ready"),
]


@pytest.fixture(scope="module")
def openapi(api_a):
    r = api_a.get("/openapi.json")
    assert r.status_code == 200
    return r.json()


def test_health_is_alive(api_a):
    r = api_a.get("/health")
    assert r.status_code == 200 and r.json().get("status") == "ok"


def test_ready_reports_real_dependencies(api_a):
    r = api_a.get("/ready")
    assert r.status_code in (200, 503)
    body = r.json()
    assert isinstance(body["ready"], bool) and (r.status_code == 200) == body["ready"]
    assert body["checks"], "readiness must list the dependencies it actually checked"


def test_openapi_is_openapi3_and_has_error_schema(openapi):
    assert openapi["openapi"].startswith("3.")
    assert "ErrorBody" in openapi.get("components", {}).get("schemas", {})


@pytest.mark.parametrize("method, path", API_MD_ROUTES)
def test_api_md_route_is_published(openapi, method, path):
    assert method in openapi["paths"].get(path, {}), f"{method.upper()} {path} missing from OpenAPI"


def test_unknown_route_uses_error_envelope(api_a):
    r = api_a.get("/api/definitely-not-a-route", headers={"x-request-id": "qa-req-1"})
    body = assert_envelope(r, 404)
    assert body["request_id"] == "qa-req-1"


def test_validation_error_is_422_envelope_without_echoing_input(api_a):
    r = api_a.post("/api/configurations", {"name": "x", "dataset_id": "y", "owner_id": "SECRET-VALUE"}, key=None)
    body = assert_envelope(r, 422)
    assert "SECRET-VALUE" not in r.text, body


def test_session_cookie_is_httponly(base_url):
    import httpx

    r = httpx.get(base_url + "/api/session")
    cookie = r.headers.get("set-cookie", "")
    assert "httponly" in cookie.lower() and "samesite" in cookie.lower(), cookie

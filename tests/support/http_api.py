"""HTTP client helpers for black-box tests (no server, no core doubles)."""
from __future__ import annotations

import os
import time
import uuid

import httpx

RUN_TIMEOUT = float(os.environ.get("QA_RUN_TIMEOUT", "300"))
FINAL = ("COMPLETED", "FAILED")


class Api:
    """One browser-like session: its own cookie jar, so two instances = two owners."""

    def __init__(self, base_url: str):
        self.http = httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=False)

    def get(self, url, **kw):
        return self.http.get(url, **kw)

    def post(self, url, json=None, key: str | None = "auto", **kw):
        headers = dict(kw.pop("headers", {}) or {})
        if key == "auto":
            key = uuid.uuid4().hex
        if key is not None:
            headers["Idempotency-Key"] = key
        return self.http.post(url, json=json, headers=headers, **kw)

    def put(self, url, json=None, **kw):
        return self.http.put(url, json=json, **kw)

    # ------------------------------------------------------------ helpers
    def session(self) -> dict:
        r = self.get("/api/session")
        assert r.status_code == 200, r.text
        return r.json()

    def dataset(self, root: str, mode: str, before: str, after: str, name: str | None = None) -> dict:
        r = self.post("/api/datasets", {"name": name or f"qa-{uuid.uuid4().hex[:6]}", "root": root, "mode": mode,
                                        "before": before, "after": after}, key=None)
        assert r.status_code == 201, r.text
        return r.json()

    def config(self, dataset_id: str, checks=None, slots=None) -> dict:
        body = {"name": f"qa-{uuid.uuid4().hex[:6]}", "dataset_id": dataset_id, "slots": slots or {}}
        if checks is not None:
            body["checks"] = checks
        r = self.post("/api/configurations", body, key=None)
        assert r.status_code == 201, r.text
        return r.json()

    def start_run(self, config_id: str) -> httpx.Response:
        return self.post("/api/runs", {"configuration_id": config_id})

    def wait(self, url: str, timeout: float = RUN_TIMEOUT) -> dict:
        deadline = time.monotonic() + timeout
        body: dict = {}
        while time.monotonic() < deadline:
            r = self.get(url)
            assert r.status_code == 200, r.text
            body = r.json()
            if body["status"] in FINAL:
                return body
            time.sleep(0.2)
        raise AssertionError(f"{url} not final after {timeout}s: {body}")

    def builtin_checks(self) -> list[dict]:
        r = self.get("/api/scripts", params={"kind": "check"})
        assert r.status_code == 200, r.text
        return [s for s in r.json() if s["source"] == "builtin"]

    def script(self, kind: str, code: str, params=None) -> httpx.Response:
        return self.post("/api/scripts", {"kind": kind, "name": f"qa-{kind}-{uuid.uuid4().hex[:6]}", "code": code,
                                          "params": params or {}}, key=None)


def assert_envelope(resp: httpx.Response, status: int | tuple[int, ...], code: str | None = None) -> dict:
    statuses = status if isinstance(status, tuple) else (status,)
    assert resp.status_code in statuses, f"{resp.status_code} {resp.text}"
    body = resp.json()
    assert set(body) >= {"code", "message", "details", "request_id"}, body
    if code:
        assert body["code"] == code, body
    return body


def known_defect(condition: bool, disc: str) -> None:
    """Expected failure ONLY for the precisely documented defect condition (CR #8).

    Anything else (5xx, other codes, broken fixtures) is not matched here and therefore fails normally.
    When the defect is fixed the condition is false and the test's real assertions run (PASS or FAIL).
    """
    import pytest

    if condition:
        pytest.xfail(disc)

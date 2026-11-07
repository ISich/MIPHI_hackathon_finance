"""TEST DOUBLE - used only by tests/selftest to prove that HTTP tests detect real defects.

A loopback reverse proxy in front of a REAL backend that injects exactly one known defect per
mutation name. It never runs in the normal HTTP suite and is not evidence of backend behaviour.

Mutations:
  summary_200_while_running - while a Run is not final, /summary and /checks answer 200 {} (instead of 409)
  pivot_500                 - POST /api/runs/{id}/pivot answers 500 INTERNAL_ERROR (instead of 501)
  trust_owner_header        - backend 'trusts' X-Owner-Id: the first cookie seen with a header value is
                              reused for every later request carrying the same header value
  lie_mode_builtin          - /api/session reports execution_mode=builtin-only although the server is
                              trusted-local (custom code really executes)
  stuck_running             - a Run that never finishes but keeps answering: GET /api/runs/{id} reports
                              RUNNING/NORMALIZING and /summary, /checks answer 409 NOT_READY
  checks_garbage_while_running - while the upstream Run is in CHECKING/FINALIZING (not final),
                              /runs/{id}/checks answers 200 {} (malformed early report)
  shared_owner_for_query    - pivot / pivot-facts/applications / groups/{g}/applications ignore the caller's
                              session: the first cookie seen on any of them is used for all later calls
  refuse_custom_config      - POST /api/configurations carrying "checks" answers 403 CUSTOM_EXECUTION_DISABLED
  checks_malformed_rows     - every 200 from /runs/{id}/checks keeps its identity fields but has checks=[{}],
                              executions=[{}]
  mode_missing              - /api/session omits execution_mode
  reject_badjson_dataset    - POST /api/datasets for the 'badjson' fixture answers 422 (early-rejection policy)
  pivot_200_no_locator      - POST /api/runs/{id}/pivot answers 200 with cells lacking any group locator
  shared_owner_for_downloads - artifact download and check-run code ignore the caller's session (first cookie wins)
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

HOP = {"connection", "keep-alive", "transfer-encoding", "content-length", "content-encoding"}


def make_proxy(upstream: str, mutations: set[str]) -> ThreadingHTTPServer:
    owner_cookie: dict[str, str] = {}
    lock = threading.Lock()
    # No shared httpx.Client: its cookie jar would merge the sessions of different callers.
    def upstream_request(method, path, content, headers):
        return httpx.request(method, upstream + path, content=content, headers=headers, timeout=60)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status: int, headers: list[tuple[str, str]], body: bytes) -> None:
            self.send_response(status)
            for k, v in headers:
                if k.lower() not in HOP:
                    self.send_header(k, v)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload) -> None:
            self._send(status, [("content-type", "application/json")], json.dumps(payload).encode())

        def _forward(self, method: str) -> None:
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length) if length else b""
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP | {"host"}}
            path = self.path
            if "trust_owner_header" in mutations and self.headers.get("x-owner-id"):
                hdr = self.headers["x-owner-id"]
                with lock:
                    cookie = owner_cookie.setdefault(hdr, self.headers.get("cookie", ""))
                if cookie:
                    headers = {k: v for k, v in headers.items() if k.lower() != "cookie"}
                    headers["cookie"] = cookie
            if "shared_owner_for_query" in mutations and re.fullmatch(
                    r"/api/runs/[^/]+/(pivot|pivot-facts/applications|groups/[^/]+/applications)", path.split("?")[0]):
                with lock:
                    cookie = owner_cookie.setdefault("__query__", self.headers.get("cookie", ""))
                headers = {k: v for k, v in headers.items() if k.lower() != "cookie"}
                headers["cookie"] = cookie
            if "shared_owner_for_downloads" in mutations and re.fullmatch(
                    r"/api/(runs/[^/]+/artifacts/[^/]+|check-runs/[^/]+/code/[^/]+)", path.split("?")[0]):
                with lock:
                    cookie = owner_cookie.setdefault("__downloads__", self.headers.get("cookie", ""))
                headers = {k: v for k, v in headers.items() if k.lower() != "cookie"}
                headers["cookie"] = cookie
            if "refuse_custom_config" in mutations and method == "POST" and path == "/api/configurations" \
                    and b'"checks"' in body:
                return self._json(403, {"code": "CUSTOM_EXECUTION_DISABLED", "message": "disabled", "details": {},
                                        "request_id": "x"})
            if "reject_badjson_dataset" in mutations and method == "POST" and path == "/api/datasets" \
                    and b"badjson" in body:
                return self._json(422, {"code": "DATASET_INVALID_JSON", "message": "invalid JSON", "details": {},
                                        "request_id": "x"})
            if "pivot_200_no_locator" in mutations and method == "POST" and re.fullmatch(r"/api/runs/[^/]+/pivot",
                                                                                          path):
                return self._json(200, {"items": [{"dimensions": {"PATH": "x"}, "cnt": 1}], "total": 1})
            if "pivot_500" in mutations and method == "POST" and re.fullmatch(r"/api/runs/[^/]+/pivot", path):
                return self._json(500, {"code": "INTERNAL_ERROR", "message": "boom", "details": {}, "request_id": "x"})
            resp = upstream_request(method, path, body, headers)
            out_headers = list(resp.headers.multi_items())
            content = resp.content
            if "summary_200_while_running" in mutations and resp.status_code == 409 and \
                    re.fullmatch(r"/api/runs/[^/]+/(summary|checks)", path.split("?")[0]):
                return self._json(200, {})
            if "stuck_running" in mutations and re.fullmatch(r"/api/runs/[^/]+/(summary|checks)", path.split("?")[0]):
                return self._json(409, {"code": "NOT_READY", "message": "not ready", "details": {},
                                        "request_id": "x"})
            if "stuck_running" in mutations and resp.status_code == 200 and re.fullmatch(r"/api/runs/[^/]+",
                                                                                          path.split("?")[0]):
                data = resp.json()
                data.update(status="RUNNING", stage="NORMALIZING", finished_at=None)
                content = json.dumps(data).encode()
            if "checks_garbage_while_running" in mutations and \
                    re.fullmatch(r"/api/runs/[^/]+/checks", path.split("?")[0]):
                run_path = path.split("?")[0].rsplit("/", 1)[0]
                upstream_run = upstream_request("GET", run_path, b"", headers).json()
                if upstream_run.get("status") not in ("COMPLETED", "FAILED") and \
                        upstream_run.get("stage") in ("CHECKING", "FINALIZING"):
                    return self._json(200, {})
            if "checks_malformed_rows" in mutations and resp.status_code == 200 and \
                    re.fullmatch(r"/api/runs/[^/]+/checks", path.split("?")[0]):
                data = resp.json()
                data.update(checks=[{}], executions=[{}])
                content = json.dumps(data).encode()
            if "mode_missing" in mutations and path.startswith("/api/session") and resp.status_code == 200:
                data = resp.json()
                data.pop("execution_mode", None)
                content = json.dumps(data).encode()
            if "lie_mode_builtin" in mutations and path.startswith("/api/session") and resp.status_code == 200:
                data = resp.json()
                data["execution_mode"] = "builtin-only"
                content = json.dumps(data).encode()
            if "lie_mode_builtin" in mutations and path.startswith("/api/script-kinds") and resp.status_code == 200:
                content = json.dumps([{**k, "custom_execution_enabled": False} for k in resp.json()]).encode()
            self._send(resp.status_code, out_headers, content)

        def do_GET(self):  # noqa: N802
            self._forward("GET")

        def do_POST(self):  # noqa: N802
            self._forward("POST")

        def do_PUT(self):  # noqa: N802
            self._forward("PUT")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server

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
            if "pivot_500" in mutations and method == "POST" and re.fullmatch(r"/api/runs/[^/]+/pivot", path):
                return self._json(500, {"code": "INTERNAL_ERROR", "message": "boom", "details": {}, "request_id": "x"})
            resp = upstream_request(method, path, body, headers)
            out_headers = list(resp.headers.multi_items())
            content = resp.content
            if "summary_200_while_running" in mutations and resp.status_code == 409 and \
                    re.fullmatch(r"/api/runs/[^/]+/(summary|checks)", path.split("?")[0]):
                return self._json(200, {})
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

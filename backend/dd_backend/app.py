"""FastAPI application factory."""
from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import errors, sessions
from .db import Database
from .readiness import readiness
from .settings import LOOPBACK_HOSTS, load_settings, split_host


def _is_loopback(addr: str) -> bool:
    import ipaddress
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False

log = logging.getLogger("dd_backend")

MAX_JSON_BODY = 2 * 1024 * 1024


class BodyLimitMiddleware:
    """Outermost ASGI layer: counts bytes while receiving; works without Content-Length (chunked)."""

    def __init__(self, app, max_code_bytes: int) -> None:
        self.app = app
        self.max_code_bytes = max_code_bytes

    def limit_for(self, content_type: str) -> int:
        return self.max_code_bytes + 64 * 1024 if "multipart" in content_type else MAX_JSON_BODY

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        limit = self.limit_for(headers.get(b"content-type", b"").decode("latin-1"))
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            total += len(body)
            if total > limit:
                return await self._reject(send, limit)
            chunks.append(body)
            if not message.get("more_body", False):
                break
        data = b"".join(chunks)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": data, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send, limit: int) -> None:
        import json as _json
        rid = secrets.token_hex(8)
        payload = _json.dumps({"code": "PAYLOAD_TOO_LARGE", "message": "Request body too large",
                               "details": {"limit_bytes": limit}, "request_id": rid}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode()),
                                (b"x-request-id", rid.encode()), (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": payload})


def _signing_key(path) -> bytes:
    """Server-generated HMAC key for D4 pivot group locators (never from a client or env).

    Published atomically: written fully to a private temp file, then hard-linked into place, so a
    concurrent starter either creates it or reads a complete key; a short key is refused.
    """
    import os
    import tempfile
    if not path.exists():
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".key-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(secrets.token_bytes(32))
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(tmp, path)
            except FileExistsError:
                pass  # another starter won; use its complete key
        finally:
            os.unlink(tmp)
    key = path.read_bytes()
    if len(key) != 32:
        raise RuntimeError(f"pivot signing key at {path.name} is corrupt ({len(key)} bytes); remove it and restart")
    return key


def create_app() -> FastAPI:
    settings = load_settings()
    db = Database(settings.db_path)
    db.init()
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    settings.scripts_dir.mkdir(parents=True, exist_ok=True)
    signing_key = _signing_key(settings.signing_key_path)

    from .registry import Registry
    registry = Registry(settings, db)
    registry.sync_builtin_scripts()

    worker = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal worker
        if settings.embedded_worker:
            from .worker import Worker
            worker = Worker(settings, db)
            worker.start_thread()
        try:
            yield
        finally:
            if worker is not None:
                worker.stop()

    app = FastAPI(
        title="Decision Diff backend (D2)",
        version="0.1.0",
        description=(
            "Platform runtime API: datasets/scripts/configurations registry, asynchronous Runs "
            "executed by a single worker, run events, artifacts, check runs and reports. "
            "Errors use the envelope {code, message, details, request_id}. "
            "Owner scope comes from the HttpOnly `dd_session` cookie only."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.registry = registry
    app.state.signing_key = signing_key
    from .runs import RunService
    app.state.runs = RunService(settings, db, registry)
    errors.install(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id", "")
        if not (0 < len(request_id) <= 64 and request_id.replace("-", "").isalnum()):
            request_id = secrets.token_hex(8)
        request.state.request_id = request_id

        def reject(status: int, code: str, message: str, details: dict | None = None):
            resp = errors.envelope(request, status, code, message, details)
            resp.headers["x-request-id"] = request_id
            return resp

        # Anti DNS-rebinding: only configured Host names (loopback by default) reach the app.
        host = split_host(request.headers.get("host", ""))
        if host not in settings.allowed_hosts:
            return reject(400, "HOST_NOT_ALLOWED", "Host header is not allowed (DD_ALLOWED_HOSTS)")
        if settings.execution_mode == "trusted-local" and not _is_loopback(request.client.host if request.client else ""):
            return reject(403, "REMOTE_CLIENT_NOT_ALLOWED", "trusted-local mode serves loopback clients only")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            # Same-origin only (no CORS): UI and API are served from one origin (nginx /api -> backend).
            # host:port of Origin must equal the Host header; scheme is ignored (TLS ends at the proxy).
            origin = request.headers.get("origin")
            if origin is not None:
                from urllib.parse import urlsplit
                netloc = urlsplit(origin.strip()).netloc.lower()
                if not netloc or netloc != request.headers.get("host", "").strip().lower():
                    return reject(403, "ORIGIN_NOT_ALLOWED",
                                  "Cross-origin requests are not supported; serve UI and API from the same origin")
            if origin is None and request.headers.get("sec-fetch-site") == "cross-site":
                return reject(403, "ORIGIN_NOT_ALLOWED", "Cross-site request rejected")
        length = request.headers.get("content-length")
        limit = settings.max_code_bytes + 64 * 1024 if "multipart" in request.headers.get("content-type", "") else MAX_JSON_BODY
        if length is not None and length.isdigit() and int(length) > limit:
            resp = errors.envelope(request, 413, "PAYLOAD_TOO_LARGE", "Request body too large", {"limit_bytes": limit})
            resp.headers["x-request-id"] = request_id
            return resp
        new_token = None
        if request.url.path.startswith("/api/"):
            owner = sessions.resolve(db, request.cookies.get(sessions.COOKIE_NAME))
            if owner is None:
                new_token, owner = sessions.create(db)
            request.state.owner_id = owner
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        if new_token is not None:
            response.set_cookie(
                sessions.COOKIE_NAME, new_token, max_age=sessions.COOKIE_MAX_AGE, httponly=True,
                samesite="lax", secure=settings.cookie_secure, path="/",
            )
        return response

    @app.get("/health", tags=["system"], summary="Process is alive")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/ready", tags=["system"], summary="Dependencies are ready (DB, core, DuckDB, checks, data roots, worker)")
    def ready():
        body = readiness(settings, db)
        return JSONResponse(status_code=200 if body["ready"] else 503, content=body)

    from .api import router
    app.include_router(router)
    app.add_middleware(BodyLimitMiddleware, max_code_bytes=settings.max_code_bytes)  # outermost
    _install_openapi(app)
    return app


def _install_openapi(app: FastAPI) -> None:
    """Make documented errors match the wire: every non-2xx /api response is the JSON ErrorBody."""
    from fastapi.openapi.utils import get_openapi

    from .models import ErrorBody
    ref = {"$ref": "#/components/schemas/ErrorBody"}

    def build():
        if app.openapi_schema:
            return app.openapi_schema
        spec = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        for path, ops in spec.get("paths", {}).items():
            if not path.startswith("/api/"):
                continue
            for op in ops.values():
                responses = op.setdefault("responses", {})
                if op.get("parameters") or op.get("requestBody"):
                    responses.setdefault("422", {"description": "Validation error"})
                for status, resp in responses.items():
                    if status.startswith("2"):
                        continue
                    resp["content"] = {"application/json": {"schema": ref}}
                    if status == "422":
                        resp["description"] = "VALIDATION_ERROR envelope"
        schemas = spec.setdefault("components", {}).setdefault("schemas", {})
        for name in ("HTTPValidationError", "ValidationError"):
            schemas.pop(name, None)
        schemas.setdefault("ErrorBody", ErrorBody.model_json_schema())
        app.openapi_schema = spec
        return spec

    app.openapi = build

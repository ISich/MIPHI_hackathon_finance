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
from .settings import load_settings

log = logging.getLogger("dd_backend")

MAX_JSON_BODY = 2 * 1024 * 1024


def create_app() -> FastAPI:
    settings = load_settings()
    db = Database(settings.db_path)
    db.init()
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    settings.scripts_dir.mkdir(parents=True, exist_ok=True)

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
    from .runs import RunService
    app.state.runs = RunService(settings, db, registry)
    errors.install(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id", "")
        if not (0 < len(request_id) <= 64 and request_id.replace("-", "").isalnum()):
            request_id = secrets.token_hex(8)
        request.state.request_id = request_id
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
    return app

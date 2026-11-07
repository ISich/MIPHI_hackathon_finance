"""Single error envelope: {code, message, details, request_id}."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("dd_backend")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def not_found(kind: str, ident: str | None = None) -> ApiError:
    # Same answer for "does not exist" and "belongs to someone else": existence is not leaked.
    return ApiError(404, "NOT_FOUND", f"{kind} not found", {"resource": kind, **({"id": ident} if ident else {})})


def not_ready(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(409, "NOT_READY", message, details)


def envelope(request: Request, status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message, "details": details or {}, "request_id": request_id},
    )


_HTTP_CODES = {400: "BAD_REQUEST", 401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND",
               405: "METHOD_NOT_ALLOWED", 409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE",
               415: "UNSUPPORTED_MEDIA_TYPE", 422: "VALIDATION_ERROR"}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return envelope(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = []
        for err in exc.errors():
            # Echo location/type/message only; never echo the submitted value (may be code/data).
            errors.append({"loc": [str(p) for p in err.get("loc", ())], "type": err.get("type"), "msg": err.get("msg")})
        return envelope(request, 422, "VALIDATION_ERROR", "Request validation failed", {"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        message = "Route not found" if exc.status_code == 404 else str(exc.detail)
        return envelope(request, exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error request_id=%s", getattr(request.state, "request_id", ""))
        return envelope(request, 500, "INTERNAL_ERROR", "Internal server error; see server log by request_id")

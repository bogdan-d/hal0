"""Structured error envelope.

All non-2xx responses follow:

    {"error": {"code": "<namespace>.<reason>", "message": "...", "details": {...}}}

Error code namespaces: slot.*, model.*, dispatch.*, config.*, system.*

This middleware catches uncaught exceptions and unhandled HTTPExceptions
and reshapes their JSON body. Handlers that raise typed `Hal0Error`
subclasses get their `code` and `details` propagated as-is.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from hal0.errors import Hal0Error

log = structlog.get_logger(__name__)


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install(app: FastAPI) -> None:
    @app.exception_handler(Hal0Error)
    async def _hal0_handler(_: Request, exc: Hal0Error) -> JSONResponse:
        log.warning("hal0.error", code=exc.code, message=exc.message, **exc.details)
        return JSONResponse(
            status_code=exc.status,
            content=_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Map FastAPI HTTPException to envelope. Code derives from status.
        code = f"system.http_{exc.status_code}"
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        log.exception("hal0.unhandled", error=str(exc))
        return JSONResponse(
            status_code=500,
            content=_envelope("system.internal", "internal server error"),
        )


__all__ = ["Hal0Error", "install"]

"""Per-request X-Request-ID middleware."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request
from starlette.responses import Response

_HEADER = "x-request-id"


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def _request_id_mw(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        req_id = request.headers.get(_HEADER) or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=req_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers[_HEADER] = req_id
        return response


__all__ = ["install"]

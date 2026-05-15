"""Log endpoints (mounted under /api/logs)."""

from __future__ import annotations

from fastapi import APIRouter

from hal0.api.middleware.error_codes import Hal0Error

router = APIRouter()


class NotImplementedYet(Hal0Error):
    code = "system.not_implemented"
    status = 501


@router.get("/api")
async def api_logs() -> dict[str, object]:
    raise NotImplementedYet("api logs: Phase 1")


@router.get("/api/stream")
async def api_logs_stream() -> dict[str, object]:
    raise NotImplementedYet("api logs stream: Phase 1")

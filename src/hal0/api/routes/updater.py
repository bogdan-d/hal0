"""Self-update endpoints (mounted under /api/updates)."""

from __future__ import annotations

from fastapi import APIRouter

from hal0.api.middleware.error_codes import Hal0Error

router = APIRouter()


class NotImplementedYet(Hal0Error):
    code = "system.not_implemented"
    status = 501


@router.get("/check")
async def check_updates() -> dict[str, object]:
    raise NotImplementedYet("check_updates: Phase 5")


@router.post("/pull")
async def pull_update() -> dict[str, object]:
    raise NotImplementedYet("pull_update: Phase 5")


@router.get("/versions")
async def list_versions() -> dict[str, object]:
    raise NotImplementedYet("list_versions: Phase 5")


@router.post("/rollback")
async def rollback() -> dict[str, object]:
    raise NotImplementedYet("rollback: Phase 5")

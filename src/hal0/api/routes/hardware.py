"""Hardware probe + stats endpoints (mounted under /api)."""

from __future__ import annotations

from fastapi import APIRouter

from hal0.api.middleware.error_codes import Hal0Error

router = APIRouter()


class NotImplementedYet(Hal0Error):
    code = "system.not_implemented"
    status = 501


@router.get("/hardware")
async def get_hardware() -> dict[str, object]:
    raise NotImplementedYet("hardware: Phase 1")


@router.post("/hardware/probe")
async def reprobe_hardware() -> dict[str, object]:
    raise NotImplementedYet("hardware/probe: Phase 1")


@router.get("/stats/hardware")
async def stats_hardware() -> dict[str, object]:
    raise NotImplementedYet("stats/hardware: Phase 1")


@router.get("/stats/slots")
async def stats_slots() -> dict[str, object]:
    raise NotImplementedYet("stats/slots: Phase 1")

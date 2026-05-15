"""First-run wizard endpoints (mounted under /api/install)."""

from __future__ import annotations

from fastapi import APIRouter

from hal0.api.middleware.error_codes import Hal0Error

router = APIRouter()


class NotImplementedYet(Hal0Error):
    code = "system.not_implemented"
    status = 501


@router.get("/state")
async def install_state() -> dict[str, object]:
    """Whether first-run wizard should show (true when no models yet)."""
    raise NotImplementedYet("install_state: Phase 4")


@router.get("/curated-models")
async def curated_models() -> list[dict[str, object]]:
    """Curated model picker list with size + license metadata."""
    raise NotImplementedYet("curated_models: Phase 4")


@router.post("/pick-default")
async def pick_default() -> dict[str, object]:
    """Download a curated model + assign to primary slot + start."""
    raise NotImplementedYet("pick_default: Phase 4")

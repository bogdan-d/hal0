"""Settings (config) endpoints (mounted under /api/settings)."""

from __future__ import annotations

from fastapi import APIRouter

from hal0.api.middleware.error_codes import Hal0Error

router = APIRouter()


class NotImplementedYet(Hal0Error):
    code = "system.not_implemented"
    status = 501


@router.get("")
async def list_settings() -> dict[str, object]:
    raise NotImplementedYet("list_settings: Phase 1")


@router.get("/schema")
async def settings_schema() -> dict[str, object]:
    raise NotImplementedYet("settings_schema: Phase 1")


@router.get("/{key}")
async def get_setting(key: str) -> dict[str, object]:
    raise NotImplementedYet(f"get_setting {key}: Phase 1")


@router.put("/{key}")
async def set_setting(key: str) -> dict[str, object]:
    raise NotImplementedYet(f"set_setting {key}: Phase 1")


@router.post("/validate")
async def validate_settings() -> dict[str, object]:
    raise NotImplementedYet("validate_settings: Phase 1")

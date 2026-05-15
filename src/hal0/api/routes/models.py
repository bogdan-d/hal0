"""Model registry endpoints (mounted under /api/models)."""

from __future__ import annotations

from fastapi import APIRouter

from hal0.api.middleware.error_codes import Hal0Error

router = APIRouter()


class NotImplementedYet(Hal0Error):
    code = "system.not_implemented"
    status = 501


@router.get("")
async def list_models() -> list[dict[str, object]]:
    raise NotImplementedYet("list_models: Phase 1")


@router.post("")
async def create_model() -> dict[str, object]:
    raise NotImplementedYet("create_model: Phase 1")


@router.get("/{model_id}")
async def get_model(model_id: str) -> dict[str, object]:
    raise NotImplementedYet(f"get_model {model_id}: Phase 1")


@router.put("/{model_id}")
async def update_model(model_id: str) -> dict[str, object]:
    raise NotImplementedYet(f"update_model {model_id}: Phase 1")


@router.delete("/{model_id}")
async def delete_model(model_id: str) -> dict[str, object]:
    raise NotImplementedYet(f"delete_model {model_id}: Phase 1")


@router.post("/{model_id}/pull")
async def pull_model(model_id: str) -> dict[str, object]:
    raise NotImplementedYet(f"pull_model {model_id}: Phase 1")

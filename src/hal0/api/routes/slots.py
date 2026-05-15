"""Slot lifecycle endpoints (mounted under /api/slots).

Phase 0 stubs return 501. Phase 1 wires these to `hal0.slots.SlotManager`.
"""

from __future__ import annotations

from fastapi import APIRouter

from hal0.api.middleware.error_codes import Hal0Error

router = APIRouter()


class NotImplementedYet(Hal0Error):
    code = "system.not_implemented"
    status = 501


@router.get("")
async def list_slots() -> list[dict[str, object]]:
    raise NotImplementedYet("list_slots: Phase 1")


@router.post("", status_code=201)
async def create_slot() -> dict[str, object]:
    """Create a new slot. Body: SlotConfig schema (Phase 1)."""
    raise NotImplementedYet("create_slot: Phase 1")


@router.get("/metrics")
async def slot_metrics() -> dict[str, object]:
    raise NotImplementedYet("slot_metrics: Phase 1")


@router.get("/capacity")
async def slot_capacity() -> dict[str, object]:
    raise NotImplementedYet("slot_capacity: Phase 1")


@router.get("/{name}")
async def get_slot(name: str) -> dict[str, object]:
    raise NotImplementedYet(f"get_slot {name}: Phase 1")


@router.delete("/{name}")
async def delete_slot(name: str) -> dict[str, object]:
    """Delete a slot. If the slot is running, it is stopped first."""
    raise NotImplementedYet(f"delete_slot {name}: Phase 1")


@router.get("/{name}/config")
async def get_slot_config(name: str) -> dict[str, object]:
    raise NotImplementedYet(f"get_slot_config {name}: Phase 1")


@router.put("/{name}/config")
async def update_slot_config(name: str) -> dict[str, object]:
    """Update a slot's config. Body: partial SlotConfig (Phase 1)."""
    raise NotImplementedYet(f"update_slot_config {name}: Phase 1")


@router.patch("/{name}/defaults")
async def update_slot_defaults(name: str) -> dict[str, object]:
    """Update slot defaults (ctx_size, temperature, etc.)."""
    raise NotImplementedYet(f"update_slot_defaults {name}: Phase 1")


@router.post("/{name}/backend")
async def set_slot_backend(name: str) -> dict[str, object]:
    """Switch a slot's backend (e.g., vulkan → rocm)."""
    raise NotImplementedYet(f"set_slot_backend {name}: Phase 1")


@router.post("/{name}/load")
async def load_slot(name: str) -> dict[str, object]:
    raise NotImplementedYet(f"load_slot {name}: Phase 1")


@router.post("/{name}/unload")
async def unload_slot(name: str) -> dict[str, object]:
    raise NotImplementedYet(f"unload_slot {name}: Phase 1")


@router.post("/{name}/restart")
async def restart_slot(name: str) -> dict[str, object]:
    raise NotImplementedYet(f"restart_slot {name}: Phase 1")


@router.post("/{name}/swap")
async def swap_slot(name: str) -> dict[str, object]:
    raise NotImplementedYet(f"swap_slot {name}: Phase 1")


@router.get("/{name}/logs")
async def slot_logs(name: str) -> dict[str, object]:
    raise NotImplementedYet(f"slot_logs {name}: Phase 1")


@router.get("/{name}/logs/stream")
async def slot_logs_stream(name: str) -> dict[str, object]:
    raise NotImplementedYet(f"slot_logs_stream {name}: Phase 1")


@router.get("/{name}/state")
async def slot_state(name: str) -> dict[str, object]:
    raise NotImplementedYet(f"slot_state {name}: Phase 1")


@router.get("/{name}/state/stream")
async def slot_state_stream(name: str) -> dict[str, object]:
    raise NotImplementedYet(f"slot_state_stream {name}: Phase 1")

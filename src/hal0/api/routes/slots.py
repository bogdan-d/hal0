"""Slot lifecycle endpoints (mounted under /api/slots).

Phase 0 stubs return 501. Phase 1 wires these to `hal0.slots.SlotManager`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from hal0.api.middleware.error_codes import Hal0Error

router = APIRouter()


class NotImplementedYet(Hal0Error):
    code = "system.not_implemented"
    status = 501


def _synthesize_slots_from_upstreams(request: Request) -> list[dict[str, Any]]:
    """Build virtual slot entries from configured upstreams.

    Until the SlotManager + hal0-slot@.service template lands in Phase 2,
    the dashboard still needs to show *something* in the Slots view —
    otherwise the user sees nothing despite real inference flowing through.
    Each upstream surfaces as a read-only slot entry: status="serving"
    when its model cache is populated, "offline" otherwise.
    """
    upstreams = request.app.state.upstreams
    cache = getattr(request.app.state, "model_cache", {})
    out: list[dict[str, Any]] = []
    for u in upstreams.list():
        models = cache.get(u.name, [])
        # Pick a representative model — prefer non-alias ids.
        from hal0.api.routes.models import _is_alias  # local to avoid cycle

        real_models = [m for m in models if not _is_alias(m)]
        primary_model = real_models[0] if real_models else (models[0] if models else "")
        out.append(
            {
                "name": u.name,
                "kind": u.kind,
                "model": primary_model,
                "status": "serving" if models else "offline",
                "backend": "remote" if u.kind == "remote" else "vulkan",
                "provider": "remote-upstream" if u.kind == "remote" else "llama-server",
                "url": u.url,
                "advertised_models": len(models),
                "_synthetic": True,
                "_synthetic_reason": (
                    "Backed by remote upstream; full slot lifecycle lands with the Phase 2 installer."
                ),
            }
        )
    return out


@router.get("")
async def list_slots(request: Request) -> list[dict[str, object]]:
    """List configured slots.

    Currently synthesizes one virtual slot per configured upstream — real
    SlotManager-backed slots wire in with the Phase 2 installer.
    """
    return _synthesize_slots_from_upstreams(request)


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

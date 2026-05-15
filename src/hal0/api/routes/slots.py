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

    The slot's ``model`` reflects the most recently dispatched model id
    for this upstream (tracked in ``app.state.last_used_model``); falls
    back to the first non-alias from the catalog before any inference
    has happened.
    """
    upstreams = request.app.state.upstreams
    cache = getattr(request.app.state, "model_cache", {})
    last_used = getattr(request.app.state, "last_used_model", {})
    out: list[dict[str, Any]] = []
    for u in upstreams.list():
        models = cache.get(u.name, [])
        from hal0.api.routes.models import _is_alias  # local to avoid cycle

        real_models = [m for m in models if not _is_alias(m)]
        primary_model = (
            last_used.get(u.name)
            or (real_models[0] if real_models else "")
            or (models[0] if models else "")
        )
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
                "last_used_model": last_used.get(u.name) or None,
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


def _local_throughput_tps(request: Request, window_s: float = 5.0) -> float:
    """Compute current tokens/sec from the rolling tps_events window.

    Rate is ``tokens / (last_event_ts − first_event_ts_in_window)`` rather
    than ``tokens / window_s`` so short bursts read at their real rate
    instead of being smeared across the full lookback. Decays to 0 once
    all events age out.
    """
    import time

    events = getattr(request.app.state, "tps_events", None)
    if not events:
        return 0.0
    now = time.monotonic()
    in_window = [(ts, tok) for ts, tok in events if now - ts <= window_s]
    if len(in_window) < 2:
        return 0.0
    total_tokens = sum(tok for _, tok in in_window)
    span = in_window[-1][0] - in_window[0][0]
    # Bias slightly toward the window so a stale-but-recent burst still
    # decays instead of pegging at peak forever.
    effective_span = max(span, (now - in_window[-1][0]))
    if effective_span <= 0:
        return 0.0
    return total_tokens / effective_span


@router.get("/metrics")
async def slot_metrics(request: Request) -> dict[str, Any]:
    """Per-slot runtime metrics keyed by slot name.

    Drives the dashboard's per-slot GTT bars + throughput sparkline.
    Proxies remote upstreams via /api/stats/slots; real local SlotManager
    metrics merge in once the manager is wired.

    Adds a synthetic ``__hal0_local__`` entry carrying current TPS
    measured from the streaming dispatcher path — covers the case where
    the upstream (e.g. FLM/NPU on haloai) doesn't report tps itself.
    """
    from hal0.api.routes.hardware import stats_slots

    merged = await stats_slots(request)
    tps = _local_throughput_tps(request)
    if tps > 0 or "__hal0_local__" not in merged:
        merged["__hal0_local__"] = {
            "name": "__hal0_local__",
            "tokens_per_sec": tps,
            "_synthetic": True,
        }
    return merged


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

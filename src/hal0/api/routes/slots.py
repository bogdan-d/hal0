"""Slot lifecycle endpoints (mounted under /api/slots).

Phase 1: real SlotManager-backed lifecycle wired alongside synthetic
upstream-backed entries. Real slots win on name collision; synthetic
entries persist for remote-upstream visibility in the dashboard until
every upstream has a corresponding local slot.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from hal0.api.middleware.error_codes import Hal0Error
from hal0.slots.manager import Slot, SlotManager

router = APIRouter()


class NotImplementedYet(Hal0Error):
    code = "system.not_implemented"
    status = 501


# ── helpers ────────────────────────────────────────────────────────────────


def _get_slot_manager(request: Request) -> SlotManager:
    """Pull the SlotManager off app.state (wired in the lifespan).

    Missing manager raises a typed system.internal so the error envelope
    middleware renders consistently — should never happen outside tests
    that bypass the lifespan.
    """
    sm = getattr(request.app.state, "slot_manager", None)
    if sm is None:
        raise Hal0Error(
            "slot_manager not initialised on app.state",
            details={"hint": "lifespan did not run"},
        )
    return sm


def _slot_to_dict(slot: Slot) -> dict[str, Any]:
    """Serialise a real Slot snapshot into the API shape.

    Adds ``kind="local"`` so the UI can distinguish real slots from the
    synthetic upstream-backed entries (which carry ``kind="remote"`` or
    similar and ``_synthetic: true``).
    """
    base = slot.as_dict()
    base["kind"] = "local"
    # Mirror the synthetic shape's top-level ``status`` field so the
    # dashboard's existing slot rendering keeps working without a branch.
    base["status"] = slot.state.value
    return base


def _synthesize_slots_from_upstreams(request: Request) -> list[dict[str, Any]]:
    """Build virtual slot entries from configured upstreams.

    Until every upstream has a corresponding local slot, the dashboard
    still needs to show remote-backed inference targets. Each upstream
    surfaces as a read-only slot entry: status="serving" when its model
    cache is populated, "offline" otherwise.

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
                    "Backed by remote upstream; install a local slot of the "
                    "same name to take over."
                ),
            }
        )
    return out


# ── list / create ──────────────────────────────────────────────────────────


@router.get("")
async def list_slots(request: Request) -> list[dict[str, object]]:
    """List configured slots.

    Merges real SlotManager-backed entries with synthetic upstream-backed
    ones. Real slots win on name collision so the dashboard sees a single
    authoritative row per slot name once a local slot is installed.
    """
    sm = _get_slot_manager(request)
    real_slots = await sm.list()
    real_entries: list[dict[str, Any]] = [_slot_to_dict(s) for s in real_slots]
    real_names = {entry["name"] for entry in real_entries}

    synthetic = _synthesize_slots_from_upstreams(request)
    merged: list[dict[str, Any]] = list(real_entries)
    for entry in synthetic:
        if entry["name"] not in real_names:
            merged.append(entry)
    return merged


@router.post("", status_code=201)
async def create_slot() -> dict[str, object]:
    """Create a new slot. Body: SlotConfig schema (Phase 1)."""
    raise NotImplementedYet("create_slot: Phase 1")


# ── metrics / capacity ─────────────────────────────────────────────────────


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


# ── per-slot ───────────────────────────────────────────────────────────────


@router.get("/{name}")
async def get_slot(name: str, request: Request) -> dict[str, object]:
    """Return a snapshot of a single slot.

    Real slots come from the SlotManager; if the name isn't a configured
    local slot, fall through to the synthetic upstream-backed entry.
    SlotNotFound surfaces as the typed slot.not_found envelope.
    """
    sm = _get_slot_manager(request)
    try:
        snap = await sm.status(name)
        return _slot_to_dict(snap)
    except Exception:
        # Fall through to synthetic lookup before re-raising — a remote
        # upstream named ``haloai`` should be observable via this endpoint
        # even though it isn't a real slot.
        for entry in _synthesize_slots_from_upstreams(request):
            if entry["name"] == name:
                return entry
        raise


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


# ── lifecycle ──────────────────────────────────────────────────────────────


@router.post("/{name}/load")
async def load_slot(name: str, request: Request) -> dict[str, object]:
    """Load a model into a slot. Optional body: {"model_id": "..."}."""
    sm = _get_slot_manager(request)
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:
        # POST without a body is fine — fall back to the slot's default model.
        body = {}
    model_id = body.get("model_id") if isinstance(body, dict) else None
    snap = await sm.load(name, model_id=model_id)
    return _slot_to_dict(snap)


@router.post("/{name}/unload")
async def unload_slot(name: str, request: Request) -> dict[str, object]:
    sm = _get_slot_manager(request)
    snap = await sm.unload(name)
    return _slot_to_dict(snap)


@router.post("/{name}/restart")
async def restart_slot(name: str, request: Request) -> dict[str, object]:
    sm = _get_slot_manager(request)
    snap = await sm.restart(name)
    return _slot_to_dict(snap)


@router.post("/{name}/swap")
async def swap_slot(name: str, request: Request) -> dict[str, object]:
    """Hot-swap a slot's model. Body: {"model_id": "..."}."""
    sm = _get_slot_manager(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    model_id = body.get("model_id") if isinstance(body, dict) else None
    if not model_id:
        raise Hal0Error(
            "swap requires a non-empty model_id in the request body",
            details={"slot": name},
        )
    snap = await sm.swap(name, model_id)
    return _slot_to_dict(snap)


# ── logs ───────────────────────────────────────────────────────────────────
#
# Real journalctl-backed log access is a Phase 2 surface — the SlotManager
# doesn't expose a logs() method today (state lives in journald, not in
# the manager). Leaving these as typed 501 stubs so a UI build that
# touches them gets a clear envelope rather than a 404.


@router.get("/{name}/logs")
async def slot_logs(name: str) -> dict[str, object]:
    raise NotImplementedYet(f"slot_logs {name}: Phase 2 (journalctl-backed)")


@router.get("/{name}/logs/stream")
async def slot_logs_stream(name: str) -> dict[str, object]:
    raise NotImplementedYet(f"slot_logs_stream {name}: Phase 2 (journalctl-backed)")


# ── state ──────────────────────────────────────────────────────────────────


@router.get("/{name}/state")
async def slot_state(name: str, request: Request) -> dict[str, object]:
    """Return just the state-machine fields for this slot.

    Lighter than /api/slots/{name} — used by clients that poll for a
    transition without needing the full metadata payload.
    """
    sm = _get_slot_manager(request)
    snap = await sm.status(name)
    return {
        "name": snap.name,
        "state": snap.state.value,
        "port": snap.port,
        "model_id": snap.model_id,
        "backend": snap.backend,
    }


@router.get("/{name}/state/stream")
async def slot_state_stream(name: str, request: Request) -> StreamingResponse:
    """SSE stream of state transitions for ``name`` (and only ``name``).

    The SlotManager's state_stream() is fanned out across all slots; this
    endpoint filters to a single slot to keep the wire chatty only where
    the UI is looking. Initial event carries the current snapshot so a
    client that subscribes after a transition still sees the latest
    state without a separate GET.

    SSE event shape::

        event: state
        data: {"name": "...", "state": "ready", "port": 8081, ...}
    """
    sm = _get_slot_manager(request)
    # Confirm the slot exists before opening the long-lived stream — keeps
    # the 404 surface fast and synchronous.
    snap = await sm.status(name)
    initial = {
        "name": snap.name,
        "state": snap.state.value,
        "port": snap.port,
        "model_id": snap.model_id,
        "backend": snap.backend,
    }

    async def event_source() -> Any:
        # Initial snapshot so late subscribers don't wait for the next
        # transition just to learn the current state.
        yield f"event: state\ndata: {json.dumps(initial)}\n\n"
        try:
            async for rec in sm.state_stream():
                if rec.name != name:
                    continue
                payload = {
                    "name": rec.name,
                    "state": rec.state.value,
                    "port": rec.port,
                    "model_id": rec.model_id,
                    "message": rec.message,
                    "updated_at": rec.updated_at,
                }
                yield f"event: state\ndata: {json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            # Client disconnected — let the generator wind down cleanly so
            # the SlotManager removes the subscriber queue.
            raise

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

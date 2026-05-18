"""Backend introspection endpoints.

Mounted under ``/api/backends`` (see :mod:`hal0.api.__init__`):

  - ``GET /api/backends``       — list every backend with its live status.
  - ``GET /api/backends/{id}``  — single-backend detail.

The shape is tuned for the dashboard's Capability-slots footer cards.
Several fields are placeholders for this round (``totalReqPerSec``
returns 0 until a stats source lands).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from hal0.api.deps import CapabilityOrchestratorDep, SlotManagerDep
from hal0.capabilities.catalog import available_backends, get_backend
from hal0.capabilities.orchestrator import _CHILD_TO_SLOT, _SLOT_TO_CHILD
from hal0.config.loader import load_hardware_info
from hal0.errors import NotFound

router = APIRouter()


# ── helpers ──────────────────────────────────────────────────────────────────


def _hardware_for_backend(backend_id: str) -> str:
    """Render the ``hardware`` field for a backend card.

    Pulls from the cached hardware probe. Returns ``"n/a"`` when the
    relevant component wasn't detected.
    """
    try:
        hw = load_hardware_info()
    except Exception:
        return "n/a"
    if backend_id == "npu":
        if hw.npu and hw.npu.present:
            return hw.npu.name or "AMD XDNA"
        return "n/a"
    if backend_id in {"gpu-vulkan", "gpu-rocm"}:
        if hw.gpus:
            return hw.gpus[0].name or hw.gpus[0].vendor or "GPU"
        return "n/a"
    if backend_id == "cpu":
        return hw.cpu_model or "CPU"
    return "n/a"


def _driver_for_backend(backend_id: str) -> str:
    """Return the driver / runtime string for the backend card."""
    try:
        hw = load_hardware_info()
    except Exception:
        return ""
    if backend_id == "npu":
        if hw.npu and hw.npu.driver:
            return hw.npu.driver
        return "amdxdna"
    if backend_id == "gpu-vulkan":
        if hw.gpus:
            return "Mesa Vulkan"
        return ""
    if backend_id == "gpu-rocm":
        if hw.gpus:
            return hw.gpus[0].driver or "ROCm"
        return ""
    if backend_id == "cpu":
        return ""
    return ""


def _mem_totals_for_backend(backend_id: str) -> tuple[int, int]:
    """Return ``(memUsedMb, memTotalMb)`` best-effort.

    ``memUsedMb`` is set to 0 in this round — wiring per-slot residency
    will piggyback on the existing slot stats surface. ``memTotalMb``
    is derived from the hardware probe so the dashboard's capacity bar
    isn't blank.
    """
    try:
        hw = load_hardware_info()
    except Exception:
        return 0, 0
    if backend_id == "npu":
        # NPU memory isn't exposed by the AMDXDNA driver yet; advertise
        # 16 GB as the Strix Halo defaults.
        return 0, 16000
    if backend_id in {"gpu-vulkan", "gpu-rocm"}:
        if hw.gpus and hw.gpus[0].vram_mb:
            return 0, hw.gpus[0].vram_mb
        if hw.unified_memory_mb:
            return 0, hw.unified_memory_mb
        return 0, 0
    if backend_id == "cpu":
        return 0, hw.ram_mb or 0
    return 0, 0


async def _loaded_children_for_backend(
    backend_id: str, slot_manager: SlotManagerDep
) -> list[dict[str, Any]]:
    """Return the children currently loaded on this backend.

    Walks every (slot, child) pair, asks SlotManager for a live
    snapshot, and surfaces the ones whose ``backend`` (translated via
    the catalog mapping) matches ``backend_id`` and are in a live state.
    """
    out: list[dict[str, Any]] = []
    for (slot, child), slot_name in _CHILD_TO_SLOT.items():
        try:
            snap = await slot_manager.status(slot_name)
        except Exception:
            continue
        # Only live slots count toward "loaded".
        if snap.state.value in {"offline", "error", "unloading"}:
            continue
        slot_backend = snap.backend or ""
        canonical = {
            "vulkan": "gpu-vulkan",
            "rocm": "gpu-rocm",
            "flm": "npu",
            "kokoro": "gpu-vulkan",
            "moonshine": "gpu-vulkan",
            "cpu": "cpu",
        }.get(slot_backend, slot_backend)
        if canonical != backend_id:
            continue
        size_mb = 0
        meta = snap.metadata or {}
        if isinstance(meta.get("size_mb"), int):
            size_mb = int(meta["size_mb"])
        out.append(
            {
                "slot": slot,
                "child": child,
                "modelId": snap.model_id or "",
                "sizeMb": size_mb,
            }
        )
    return out


def _state_for_backend(backend_id: str) -> str:
    """Return ``ready`` / ``offline`` / ``error`` for the backend card."""
    available_ids = {b["id"] for b in available_backends()}
    if backend_id in available_ids:
        return "ready"
    return "offline"


# ── routes ────────────────────────────────────────────────────────────────────


async def _build_backend_payload(
    backend: dict[str, Any], slot_manager: SlotManagerDep
) -> dict[str, Any]:
    """Render one backend descriptor + live status into the response shape."""
    backend_id = backend["id"]
    mem_used, mem_total = _mem_totals_for_backend(backend_id)
    loaded = await _loaded_children_for_backend(backend_id, slot_manager)
    return {
        "id": backend_id,
        "label": backend.get("label", backend_id),
        "short": backend.get("short", backend_id),
        "provider": backend.get("provider", ""),
        "multiplex": bool(backend.get("multiplex", False)),
        "hardware": _hardware_for_backend(backend_id),
        "driver": _driver_for_backend(backend_id),
        "state": _state_for_backend(backend_id),
        "memUsedMb": mem_used,
        "memTotalMb": mem_total,
        "totalReqPerSec": 0,
        "loaded": loaded,
    }


@router.get("")
async def list_backends(
    request: Request, slot_manager: SlotManagerDep
) -> list[dict[str, Any]]:
    """Return one row per available backend with live status."""
    out: list[dict[str, Any]] = []
    for backend in available_backends():
        out.append(await _build_backend_payload(backend, slot_manager))
    return out


@router.get("/{backend_id}")
async def get_backend_details(
    backend_id: str,
    request: Request,
    slot_manager: SlotManagerDep,
) -> dict[str, Any]:
    """Single-backend variant of :func:`list_backends`."""
    backend = get_backend(backend_id)
    if backend is None:
        raise NotFound(
            f"backend {backend_id!r} not available on this host",
            code="backend.not_found",
            details={"id": backend_id},
        )
    return await _build_backend_payload(backend, slot_manager)


__all__ = ["router"]

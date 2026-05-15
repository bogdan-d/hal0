"""Hardware probe + stats endpoints (mounted under /api)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from hal0.config import paths
from hal0.config.loader import load_hardware_info

router = APIRouter()


def _flatten_for_ui(info: dict[str, Any]) -> dict[str, Any]:
    """Project HardwareInfo into the fields the Vue Hardware view expects.

    The dashboard reads ``gpu_name``, ``vram_total_mb``, ``gtt_total_mb``,
    etc. — flat shapes from haloai's old stats dict.  We keep the full
    pydantic model under ``info`` so future views can opt into the richer
    schema without breaking the current view.
    """
    gpus = info.get("gpus") or []
    primary_gpu = gpus[0] if gpus else {}
    return {
        **info,
        "gpu_name": primary_gpu.get("name", ""),
        "gpu_vendor": primary_gpu.get("vendor", ""),
        "vram_total_mb": primary_gpu.get("vram_mb", 0),
        "gtt_total_mb": primary_gpu.get("vram_mb", 0),
        "ram_total_mb": info.get("ram_mb", 0),
        "ram_available_mb": info.get("ram_available_mb", 0),
        "disk_free_mb": info.get("disk_free_mb", 0),
        "cpu_name": info.get("cpu_model", ""),
        "cpu_cores": info.get("cpu_cores", 0),
        "cpu_threads": info.get("cpu_threads", 0),
        "npu_present": (info.get("npu") or {}).get("present", False),
        "npu_name": (info.get("npu") or {}).get("name", ""),
    }


@router.get("/hardware")
async def get_hardware(request: Request) -> dict[str, Any]:
    """Return cached /etc/hal0/hardware.json, falling back to a fresh probe.

    The probe is heavy enough (subprocess fanout) that we prefer the
    cached snapshot; ``POST /api/hardware/probe`` forces a re-run.
    """
    target = paths.hardware_json()
    if target.exists():
        try:
            info = load_hardware_info().model_dump(mode="python")
            return _flatten_for_ui(info)
        except Exception:
            pass
    # Cache miss → probe now.
    probe = request.app.state.hardware_probe
    info = (await probe.probe_async()).model_dump(mode="python")
    return _flatten_for_ui(info)


@router.post("/hardware/probe")
async def reprobe_hardware(request: Request) -> dict[str, Any]:
    """Re-run the hardware probe and persist to /etc/hal0/hardware.json."""
    probe = request.app.state.hardware_probe
    info = await probe.probe_async()
    probe.write(info)
    return _flatten_for_ui(info.model_dump(mode="python"))


@router.get("/stats/hardware")
async def stats_hardware(request: Request) -> dict[str, Any]:
    """Runtime hardware stats (RAM/VRAM/disk used, GPU util, etc.)."""
    # NOTE: a real implementation reads /proc and GPU sysfs each call;
    # for now we surface what /api/hardware already exposes.
    return await get_hardware(request)


@router.get("/stats/slots")
async def stats_slots(request: Request) -> dict[str, Any]:
    slot_mgr = getattr(request.app.state, "slot_manager", None)
    if slot_mgr is None:
        return {"slots": []}
    try:
        slots = await slot_mgr.list() if hasattr(slot_mgr, "list") else []
    except Exception:
        slots = []
    return {"slots": slots}

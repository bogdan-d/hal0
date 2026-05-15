"""Slot capacity snapshot.

CapacitySnapshot is the single-source view of available VRAM, system RAM, and
slot budget used by:
  - GET /api/slots/capacity
  - The hardware-aware slot config form in the dashboard (VRAM fit warnings)
  - SlotManager.spawn() pre-flight checks

Port target: haloai lib/capacity.py.

Tier 1 fixes baked in (PLAN.md §5):
  - No silent exception swallow.  Bad TOML / missing meminfo surface as
    typed SlotConfigError / SlotError, not a degraded ``"?"`` row.  Callers
    that *want* graceful degradation (e.g. the dashboard) catch at the
    boundary.
  - All memory units are MiB.  haloai mixed GiB and MiB across the same
    call graph; this module standardises and the dashboard divides by
    1024.0 at render time.

See PLAN.md §3 (module port plan).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hal0.slots.state import SlotError

if TYPE_CHECKING:
    from hal0.hardware.probe import HardwareInfo


# NOTE: We code against ``hal0.hardware.probe.HardwareInfo`` as the contract
# even though the probe itself is currently a stub (raises NotImplementedError).
# When the hardware/probe agent lands real detection, capacity becomes a
# read-only consumer with no API change required.


class CapacityProbeError(SlotError):
    """/proc/meminfo unreadable, or DRM sysfs not enumerable."""

    code = "slot.capacity_probe_failed"
    status = 500


def _read_meminfo() -> tuple[float, float]:
    """Return (total_mib, available_mib) from /proc/meminfo.

    Raises CapacityProbeError on any IO error — Tier 1 fix replaces
    haloai's silent ``except OSError: pass`` at lib/capacity.py:51.
    """
    total_kib = avail_kib = 0
    path = Path("/proc/meminfo")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CapacityProbeError(
            f"failed to read /proc/meminfo: {exc}",
            details={"path": str(path)},
        ) from exc

    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            try:
                total_kib = int(line.split()[1])
            except (IndexError, ValueError) as exc:
                raise CapacityProbeError(
                    f"malformed MemTotal line in /proc/meminfo: {line!r}",
                ) from exc
        elif line.startswith("MemAvailable:"):
            try:
                avail_kib = int(line.split()[1])
            except (IndexError, ValueError) as exc:
                raise CapacityProbeError(
                    f"malformed MemAvailable line in /proc/meminfo: {line!r}",
                ) from exc
    if total_kib == 0:
        raise CapacityProbeError("MemTotal missing from /proc/meminfo")
    # KiB → MiB (kernel reports kB but they are KiB by long-standing convention).
    return total_kib / 1024.0, avail_kib / 1024.0


@dataclass
class CapacitySnapshot:
    """Point-in-time view of system and slot capacity.

    All memory values are in mebibytes (MiB) to match the sysfs and DRM
    fdinfo units used during probe.  Callers converting to GiB for display
    should divide by 1024.0.
    """

    free_vram_mb: float
    """VRAM / GTT available for new model loads, in MiB.

    On Strix Halo (UMA), this reflects the GTT pool minus current slot
    allocations (as reported by DRM fdinfo).  On NVIDIA, reads from NVML.
    """

    free_ram_mb: float
    """System RAM available (MemAvailable from /proc/meminfo), in MiB.

    Useful for CPU-fallback slots and context buffers.
    """

    total_ram_mb: float
    """Total system RAM (MemTotal from /proc/meminfo), in MiB."""

    total_vram_mb: float
    """Total VRAM / GTT, in MiB.  On UMA, equal to total_ram_mb."""

    used_slots: int
    """Number of slots currently in a non-offline state."""

    max_slots: int
    """Maximum number of concurrent slots permitted by hal0.toml
    [slots].max_slots.  0 means unconfigured / unlimited.
    """

    per_slot: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Per-slot breakdown: {slot_name: {vram_mb, ram_mb, state, model_id}}."""

    def fits(self, required_vram_mb: float, required_ram_mb: float = 0.0) -> bool:
        """Return True if the requested memory would fit within current headroom.

        Does not account for fragmentation.  On UMA hardware, free_ram_mb
        and free_vram_mb are linked — over-allocating one starves the
        other.  The dashboard's slot form is responsible for surfacing
        that subtlety.
        """
        # TIER1: No silent return — explicit comparison so the caller can
        # rely on a bool, not a maybe-truthy dict.
        if required_vram_mb < 0 or required_ram_mb < 0:
            raise CapacityProbeError(
                "fits() requirements must be non-negative",
                details={
                    "required_vram_mb": required_vram_mb,
                    "required_ram_mb": required_ram_mb,
                },
            )
        if required_vram_mb > self.free_vram_mb:
            return False
        if required_ram_mb > self.free_ram_mb:
            return False
        return not (self.max_slots and self.used_slots >= self.max_slots)

    @classmethod
    async def probe(
        cls,
        *,
        hardware_info: HardwareInfo | None = None,
        per_slot: dict[str, dict[str, Any]] | None = None,
        max_slots: int = 0,
    ) -> CapacitySnapshot:
        """Read current system state and return a fresh snapshot.

        Args:
            hardware_info: Optional pre-probed HardwareInfo.  When None, we
                read /proc/meminfo only and treat VRAM == total RAM (the
                UMA fallback used on Strix Halo when the hardware probe
                hasn't completed yet).
            per_slot: Optional pre-collected per-slot metrics.  When None,
                returns an empty mapping (the slot manager populates this).
            max_slots: hal0.toml [slots].max_slots, 0 means unlimited.

        Reads /proc/meminfo synchronously inside ``run_in_executor`` so it
        does not block the event loop.
        """
        loop = asyncio.get_running_loop()
        total_ram_mb, avail_ram_mb = await loop.run_in_executor(None, _read_meminfo)

        # Resolve VRAM / GTT.  We code against the HardwareInfo schema but
        # gracefully degrade to RAM-as-VRAM when the probe hasn't run yet —
        # PLAN.md notes UMA hardware (Strix Halo) reports the same number.
        if hardware_info is not None and hardware_info.gpus:
            total_vram_mb = float(hardware_info.gpus[0].vram_mb) or total_ram_mb
        else:
            total_vram_mb = total_ram_mb

        per_slot_map = per_slot or {}
        # free_vram_mb = total_vram_mb - sum(per-slot vram).  Clamped at 0.
        used_vram_mb = 0.0
        used_slots = 0
        for entry in per_slot_map.values():
            try:
                used_vram_mb += float(entry.get("vram_mb", 0) or 0)
            except (TypeError, ValueError) as exc:
                raise CapacityProbeError(
                    "per-slot vram_mb is not numeric",
                    details={"entry": entry},
                ) from exc
            if entry.get("state") and entry.get("state") != "offline":
                used_slots += 1
        free_vram_mb = max(total_vram_mb - used_vram_mb, 0.0)

        return cls(
            free_vram_mb=round(free_vram_mb, 1),
            free_ram_mb=round(avail_ram_mb, 1),
            total_ram_mb=round(total_ram_mb, 1),
            total_vram_mb=round(total_vram_mb, 1),
            used_slots=used_slots,
            max_slots=max_slots,
            per_slot=per_slot_map,
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict for API responses."""
        return {
            "free_vram_mb": self.free_vram_mb,
            "free_ram_mb": self.free_ram_mb,
            "total_ram_mb": self.total_ram_mb,
            "total_vram_mb": self.total_vram_mb,
            "used_slots": self.used_slots,
            "max_slots": self.max_slots,
            "per_slot": self.per_slot,
        }


__all__ = [
    "CapacityProbeError",
    "CapacitySnapshot",
]

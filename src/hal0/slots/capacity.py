"""Slot capacity snapshot.

CapacitySnapshot is the single-source view of available VRAM, system RAM, and
slot budget used by:
  - GET /api/slots/capacity
  - The hardware-aware slot config form in the dashboard (VRAM fit warnings)
  - SlotManager.spawn() pre-flight checks

Port target: haloai lib/capacity.py.

See PLAN.md §3 (module port plan).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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

        Does not account for fragmentation.

        Raises: NotImplementedError until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/capacity.py")

    @classmethod
    async def probe(cls) -> CapacitySnapshot:
        """Read current system state and return a fresh snapshot.

        Reads DRM sysfs (or NVML for NVIDIA) and /proc/meminfo.

        Raises: NotImplementedError until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/capacity.py")

    def as_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict for API responses."""
        return {
            "free_vram_mb": self.free_vram_mb,
            "free_ram_mb": self.free_ram_mb,
            "used_slots": self.used_slots,
            "max_slots": self.max_slots,
            "per_slot": self.per_slot,
        }

"""Hardware runtime stats — GPU utilisation, RAM usage, etc.

HardwareStats provides live metrics for:
  - GET /api/stats/gpu
  - GET /api/stats/ram
  - The Hardware dashboard view live numbers
  - CapacitySnapshot.probe()

Port target: haloai lib/hardware.py (split: probe + stats).
See PLAN.md §3.
"""

from __future__ import annotations

from typing import Any


class HardwareStats:
    """Live hardware metrics reader.

    Reads from sysfs, /proc/meminfo, and (on NVIDIA) NVML.  All methods
    are synchronous; wrap in asyncio.to_thread() for async callers.
    """

    def gpu_util(self) -> float | None:
        """Return current GPU compute utilisation as a fraction [0.0, 1.0].

        Returns None if the metric is unavailable (e.g. no driver support).

        Raises:
            NotImplementedError: Until Phase 1 port from haloai lib/hardware.py.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/hardware.py")

    def gpu_vram_used_mb(self) -> float | None:
        """Return current GPU VRAM usage in MiB.

        On AMD UMA (Strix Halo), returns GTT used from sysfs.
        Returns None if unavailable.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/hardware.py")

    def gpu_vram_total_mb(self) -> float | None:
        """Return total GPU VRAM in MiB.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/hardware.py")

    def ram_used_gb(self) -> float:
        """Return current system RAM used in GiB (MemTotal - MemAvailable).

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/hardware.py")

    def ram_available_gb(self) -> float:
        """Return current system RAM available in GiB (MemAvailable).

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/hardware.py")

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe dict of all available stats.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/hardware.py")

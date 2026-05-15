"""Hardware probe — detect GPU, NPU, RAM, disk, and CPU.

HardwareProbe.probe() writes a HardwareInfo snapshot to
/etc/hal0/hardware.json on first install (via the installer), and can be
re-triggered via `hal0 probe` or the "re-probe" button on the Hardware
dashboard view.

Port target: haloai lib/hardware.py (split: probe + stats).
See PLAN.md §3 and §7 (installer: "Hardware probe → /etc/hal0/hardware.json
+ default slot configs derived from detected NPU/GPU").
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GPUInfo(BaseModel):
    """Detected GPU hardware summary."""

    model_config = {"populate_by_name": True}

    vendor: str = Field(
        default="", description="GPU vendor: 'amd', 'nvidia', 'intel', or 'unknown'."
    )
    name: str = Field(default="", description="GPU model name, e.g. 'Radeon 890M'.")
    vram_mb: float = Field(default=0.0, description="Total VRAM in MiB (or GTT pool for UMA).")
    driver: str = Field(default="", description="Driver name: 'amdgpu', 'nvidia', 'i915', etc.")
    drm_path: str = Field(
        default="", description="DRM sysfs path, e.g. '/sys/class/drm/card1/device'."
    )
    compute_capable: bool = Field(default=False, description="True if ROCm/CUDA is available.")
    vulkan_capable: bool = Field(default=False, description="True if Vulkan is available.")


class NPUInfo(BaseModel):
    """Detected NPU hardware summary."""

    model_config = {"populate_by_name": True}

    present: bool = Field(default=False, description="True if an NPU was detected.")
    vendor: str = Field(default="", description="NPU vendor, e.g. 'amd'.")
    name: str = Field(default="", description="NPU name, e.g. 'AMD NPU (Phoenix / Hawk Point)'.")
    driver: str = Field(default="", description="Driver name, e.g. 'amdxdna'.")


class HardwareInfo(BaseModel):
    """Full hardware snapshot written to /etc/hal0/hardware.json.

    Produced by HardwareProbe.probe() and consumed by:
      - GET /api/hardware
      - The Hardware dashboard view
      - SlotManager capacity pre-flight checks
      - The installer's default slot config generator
    """

    model_config = {"populate_by_name": True}

    gpu: GPUInfo = Field(default_factory=GPUInfo)
    npu: NPUInfo = Field(default_factory=NPUInfo)
    ram_gb: float = Field(default=0.0, description="Total system RAM in GiB.")
    disk_gb: float = Field(default=0.0, description="Free disk space in /var/lib/hal0 in GiB.")
    cpu: str = Field(default="", description="CPU model string from /proc/cpuinfo.")
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Probe-time extras (kernel version, OS, etc.).",
    )


class HardwareProbe:
    """Detects hardware and produces a HardwareInfo snapshot.

    The probe is intentionally synchronous (subprocess + sysfs reads) and
    runs in a threadpool when called from an async context.
    """

    def probe(self) -> HardwareInfo:
        """Run hardware detection and return a HardwareInfo snapshot.

        Detects: GPU (AMD DRM sysfs / NVML), NPU (amdxdna presence),
        RAM (/proc/meminfo), disk (statvfs on /var/lib/hal0), CPU
        (/proc/cpuinfo).

        The result is suitable for direct JSON serialisation and writing to
        /etc/hal0/hardware.json.

        Raises:
            NotImplementedError: Until Phase 1 port from haloai lib/hardware.py.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/hardware.py")

    async def probe_async(self) -> HardwareInfo:
        """Async wrapper that runs probe() in a threadpool executor.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/hardware.py")

"""Hardware probe — detect GPU, NPU, RAM, disk, and CPU.

HardwareProbe.probe() writes a HardwareInfo snapshot to
/etc/hal0/hardware.json on first install (via the installer), and can be
re-triggered via `hal0 probe` or the "re-probe" button on the Hardware
dashboard view.

Port target: haloai lib/hardware.py (split: probe + stats).
See PLAN.md §3 and §7 (installer: "Hardware probe → /etc/hal0/hardware.json
+ default slot configs derived from detected NPU/GPU").

HardwareInfo / GPUInfo / NPUInfo are defined in hal0.config.schema (the
canonical home per PLAN §3); this module re-exports them so callers can
``from hal0.hardware.probe import HardwareInfo`` if they prefer.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import structlog

from hal0.errors import Hal0Error
from hal0.config import paths as _paths
from hal0.config.schema import GPUInfo, HardwareInfo, NPUInfo

log = structlog.get_logger(__name__)


class HardwareProbeError(Hal0Error):
    """Raised when the probe cannot run at all (rare — most failures degrade)."""

    code = "system.probe_failed"
    status = 500


# ── Low-level helpers ──────────────────────────────────────────────────────────


def _run(cmd: list[str], timeout: float = 4.0) -> tuple[int, str, str]:
    """Run a subprocess, capturing stdout/stderr. Never raises; returns (-1, '', err) on failure.

    # NOTE: callers must inspect the return code; we do NOT swallow into "" so
    # the higher-level helpers can decide whether to log at debug or warn.
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return -1, "", f"binary not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s: {' '.join(cmd)}"
    except OSError as exc:
        return -1, "", f"{type(exc).__name__}: {exc}"


def _read_text(path: Path) -> str | None:
    """Read a file; return None on any I/O error (never raises)."""
    try:
        return path.read_text()
    except OSError:
        return None


def _read_sysfs_mb(path: Path) -> float | None:
    """Read a sysfs byte counter and return MiB, or None on failure.

    # TIER2: returns Optional[float] rather than 0.0 on parse failure so call
    # sites can distinguish "unknown" from "actually zero" (per PLAN §5 Tier 2,
    # the _drm_mem() polish item).
    """
    txt = _read_text(path)
    if txt is None:
        return None
    try:
        return round(int(txt.strip()) / (1024 * 1024), 1)
    except ValueError:
        log.debug("hardware.probe.sysfs_parse_fail", path=str(path), raw=txt[:40])
        return None


def _amd_drm_device() -> Path | None:
    """Find the first AMD DRM card whose sysfs exports VRAM totals."""
    try:
        for p in sorted(Path("/sys/class/drm").glob("card*/device/mem_info_vram_total")):
            return p.parent
    except OSError:
        return None
    return None


# ── CPU + RAM ──────────────────────────────────────────────────────────────────


def _parse_cpuinfo() -> tuple[str, int, int]:
    """Return (model_name, physical_cores, logical_threads).

    Reads /proc/cpuinfo. Falls back to os.cpu_count() for threads if parsing fails.
    """
    txt = _read_text(Path("/proc/cpuinfo"))
    model = ""
    threads = 0
    physical_ids: set[str] = set()
    cores_per_socket = 0
    if txt:
        for line in txt.splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            if k == "model name" and not model:
                model = v
            elif k == "processor":
                threads += 1
            elif k == "physical id":
                physical_ids.add(v)
            elif k == "cpu cores":
                with contextlib.suppress(ValueError):
                    cores_per_socket = max(cores_per_socket, int(v))
    if threads == 0:
        threads = os.cpu_count() or 0
    sockets = max(1, len(physical_ids))
    cores = cores_per_socket * sockets if cores_per_socket > 0 else threads
    return model, cores, threads


def _parse_meminfo() -> tuple[int, int]:
    """Return (total_mb, available_mb) from /proc/meminfo, (0, 0) on failure."""
    txt = _read_text(Path("/proc/meminfo"))
    if not txt:
        return 0, 0
    total_kb = 0
    avail_kb = 0
    for line in txt.splitlines():
        if line.startswith("MemTotal:"):
            with contextlib.suppress(IndexError, ValueError):
                total_kb = int(line.split()[1])
        elif line.startswith("MemAvailable:"):
            with contextlib.suppress(IndexError, ValueError):
                avail_kb = int(line.split()[1])
    return total_kb // 1024, avail_kb // 1024


_SIZE_UNITS_MB = {"KB": 1 / 1024, "MB": 1, "GB": 1024, "TB": 1024 * 1024}


def _dmidecode_host_ram_mb() -> int | None:
    """Sum physical DIMM sizes via `dmidecode -t memory`.

    Used to recover the true host RAM when /proc/meminfo reflects an LXC
    cgroup quota rather than the physical pool. Returns None when
    dmidecode is unavailable or returns no usable Memory Device entries.
    """
    rc, out, _ = _run(["dmidecode", "-t", "memory"], timeout=4.0)
    if rc != 0 or not out:
        return None
    total_mb = 0.0
    in_device = False
    for raw in out.splitlines():
        line = raw.strip()
        if line.startswith("Memory Device") or line == "Memory Device":
            in_device = True
            continue
        if not in_device:
            continue
        if not line:
            in_device = False
            continue
        if line.startswith("Size:"):
            val = line.split(":", 1)[1].strip()
            if val.startswith("No Module") or val == "Unknown" or val.startswith("0 "):
                continue
            parts = val.split()
            if len(parts) >= 2:
                try:
                    n = float(parts[0])
                except ValueError:
                    continue
                unit = parts[1].upper()
                mult = _SIZE_UNITS_MB.get(unit)
                if mult:
                    total_mb += n * mult
    if total_mb <= 0:
        return None
    return int(round(total_mb))


def _derive_unified_memory_mb(ram_mb: int, gpu: GPUInfo | None) -> int:
    """Compute the true unified-memory pool size in MiB.

    On AMD UMA (Strix Halo etc.) the dedicated VRAM is a tiny BAR carve-out
    and the bulk of GPU memory comes from the GTT pool, which is *shared*
    with system RAM. Summing ram_mb + vram_mb would double-count.

    Strategy (in order):
      1. If running in an LXC where /proc/meminfo shows a cgroup quota
         smaller than the host's physical RAM, prefer dmidecode's DIMM sum.
      2. Otherwise return /proc/meminfo's MemTotal (already the right pool
         on bare metal / VMs that see all physical RAM).
      3. On non-UMA hardware (discrete GPUs), unified pool = ram_mb;
         consumers add dedicated VRAM separately.
    """
    dmi = _dmidecode_host_ram_mb()
    if dmi is not None and dmi > ram_mb * 1.1:
        # /proc/meminfo is reporting a cgroup-restricted view; trust the DIMMs.
        return dmi
    return ram_mb


# ── GPU detection ──────────────────────────────────────────────────────────────


def _detect_nvidia() -> GPUInfo | None:
    """Probe nvidia-smi. Returns a populated GPUInfo or None if no NVIDIA GPU."""
    rc, out, err = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    if rc != 0 or not out.strip():
        if rc == -1:
            log.debug("hardware.probe.nvidia_smi_unavailable", err=err)
        return None
    first = out.strip().splitlines()[0]
    parts = [p.strip() for p in first.split(",")]
    if len(parts) < 2:
        return None
    name = parts[0]
    try:
        vram_mb = round(float(parts[1]))
    except ValueError:
        vram_mb = 0
    driver = parts[2] if len(parts) >= 3 else ""
    return GPUInfo(
        vendor="nvidia",
        name=name,
        vram_mb=vram_mb,
        driver=f"nvidia {driver}".strip(),
        compute_capable=True,  # nvidia-smi presence => CUDA capable
    )


def _detect_amd() -> GPUInfo | None:
    """Probe AMD GPU via DRM sysfs and (optionally) rocm-smi.

    On Strix Halo (UMA) the vram_total counter reports the small carve-out;
    the real model-loading pool is GTT. We pick the larger of vram_total and
    gtt_total so the slot-form's "will it fit" check uses the right number.
    """
    drm = _amd_drm_device()
    if drm is None:
        return None
    vram_total = _read_sysfs_mb(drm / "mem_info_vram_total") or 0.0
    gtt_total = _read_sysfs_mb(drm / "mem_info_gtt_total") or 0.0
    effective_mb = round(max(vram_total, gtt_total))

    # Name via lspci on the device's PCI slot
    name = ""
    try:
        pci_link = (drm / "uevent").read_text()
        m = re.search(r"PCI_SLOT_NAME=(\S+)", pci_link)
        if m:
            rc, out, _ = _run(["lspci", "-s", m.group(1)])
            if rc == 0 and out:
                # e.g. "c5:00.0 VGA compatible controller: AMD ... [Radeon 890M] (rev cc)"
                after = out.split(":", 2)[-1].strip()
                name = after
    except OSError:
        pass

    # ROCm probe (very lightweight — just presence of binary + non-error exit)
    rc, _, _ = _run(["rocm-smi", "--showproductname"])
    compute_capable = rc == 0

    return GPUInfo(
        vendor="amd",
        name=name or "AMD GPU",
        vram_mb=effective_mb,
        driver="amdgpu",
        drm_path=str(drm),
        compute_capable=compute_capable,
        vulkan_capable=True,  # amdgpu ships Mesa Vulkan
    )


def _detect_vulkan_fallback() -> GPUInfo | None:
    """Use vulkaninfo to identify the primary GPU when vendor probes failed."""
    rc, out, _ = _run(["vulkaninfo", "--summary"], timeout=6.0)
    if rc != 0 or not out:
        return None
    # First "deviceName = ..." line wins.
    name = ""
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("deviceName"):
            _, _, val = line.partition("=")
            name = val.strip()
            break
    if not name:
        return None
    vendor = "unknown"
    lower = name.lower()
    if "nvidia" in lower:
        vendor = "nvidia"
    elif "amd" in lower or "radeon" in lower:
        vendor = "amd"
    elif "intel" in lower:
        vendor = "intel"
    return GPUInfo(vendor=vendor, name=name, vulkan_capable=True)


def _detect_lspci_fallback() -> GPUInfo | None:
    """Last-resort: parse `lspci -nnk` for a VGA controller."""
    rc, out, _ = _run(["lspci", "-nnk"])
    if rc != 0 or not out:
        return None
    for line in out.splitlines():
        if "VGA compatible controller" in line or "3D controller" in line:
            after = line.split(":", 2)[-1].strip()
            lower = after.lower()
            vendor = "unknown"
            if "nvidia" in lower:
                vendor = "nvidia"
            elif "amd" in lower or "ati" in lower or "radeon" in lower:
                vendor = "amd"
            elif "intel" in lower:
                vendor = "intel"
            return GPUInfo(vendor=vendor, name=after)
    return None


def _detect_gpu() -> GPUInfo:
    """Run vendor probes in order; return an empty GPUInfo if nothing matched."""
    for fn in (_detect_nvidia, _detect_amd, _detect_vulkan_fallback, _detect_lspci_fallback):
        try:
            info = fn()
        except Exception as exc:  # defensive: never let one probe crash the rest
            log.warning("hardware.probe.detector_fail", detector=fn.__name__, error=str(exc))
            continue
        if info is not None:
            return info
    return GPUInfo(vendor="unknown")


# ── NPU detection ──────────────────────────────────────────────────────────────


def _detect_npu() -> NPUInfo:
    """Detect AMD XDNA NPU presence via sysfs / /dev nodes.

    Strix Halo / Hawk Point / Phoenix expose /dev/accel/accel* once the amdxdna
    driver is loaded. We don't run `flm validate` here — that's stats territory.
    """
    accel = Path("/dev/accel")
    if accel.exists():
        try:
            entries = list(accel.iterdir())
            if entries:
                return NPUInfo(
                    present=True,
                    vendor="amd",
                    name="AMD NPU (XDNA)",
                    driver="amdxdna",
                )
        except OSError:
            pass
    # Some kernels expose it through /sys/class/accel
    if Path("/sys/module/amdxdna").exists():
        return NPUInfo(present=True, vendor="amd", name="AMD NPU (XDNA)", driver="amdxdna")
    return NPUInfo(present=False)


# ── Disk ───────────────────────────────────────────────────────────────────────


def _disk_free_mb(path: Path) -> int:
    """Return free MiB on the filesystem hosting `path`. 0 if unavailable."""
    try:
        # path may not yet exist (fresh install); walk up to the first existing parent.
        target = path
        while not target.exists() and target != target.parent:
            target = target.parent
        usage = shutil.disk_usage(str(target))
        return usage.free // (1024 * 1024)
    except OSError as exc:
        log.warning("hardware.probe.disk_fail", path=str(path), error=str(exc))
        return 0


# ── HardwareProbe ──────────────────────────────────────────────────────────────


class HardwareProbe:
    """Detects hardware and produces a HardwareInfo snapshot.

    The probe is intentionally synchronous (subprocess + sysfs reads) and
    runs in a threadpool when called from an async context.
    """

    def probe(self) -> HardwareInfo:
        """Run hardware detection and return a HardwareInfo snapshot.

        Detects: GPU (NVIDIA / AMD / Vulkan / lspci fallbacks), NPU
        (/dev/accel + amdxdna), RAM (/proc/meminfo), disk (statvfs on
        HAL0 var_lib), CPU (/proc/cpuinfo).

        Never raises for individual probe failures — each detector returns
        an empty result and logs a warning. Only catastrophic failures
        (e.g. /proc not mounted) raise HardwareProbeError.
        """
        try:
            cpu_model, cpu_cores, cpu_threads = _parse_cpuinfo()
            ram_total_mb, ram_avail_mb = _parse_meminfo()
            gpu = _detect_gpu()
            npu = _detect_npu()
            disk_mb = _disk_free_mb(_paths.var_lib())

            uname = ""
            try:
                uname_txt = _read_text(Path("/proc/version"))
                if uname_txt:
                    uname = uname_txt.strip().split(" (", 1)[0]
            except OSError:
                pass

            unified_mb = _derive_unified_memory_mb(ram_total_mb, gpu if gpu.vendor else None)

            return HardwareInfo(
                cpu_model=cpu_model,
                cpu_cores=cpu_cores,
                cpu_threads=cpu_threads,
                ram_mb=ram_total_mb,
                ram_available_mb=ram_avail_mb,
                unified_memory_mb=unified_mb,
                gpus=[gpu] if gpu.vendor else [],
                npu=npu,
                disk_free_mb=disk_mb,
                probed_at=_dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
                extra={"kernel": uname} if uname else {},
            )
        except Exception as exc:
            # We never expect to reach here — every detector is wrapped — but if
            # /proc itself is unreadable, surface a typed error rather than
            # crashing with an opaque trace.
            raise HardwareProbeError(
                "hardware probe failed", {"error": f"{type(exc).__name__}: {exc}"}
            ) from exc

    async def probe_async(self) -> HardwareInfo:
        """Async wrapper that runs probe() in a threadpool executor."""
        return await asyncio.to_thread(self.probe)

    def write(self, info: HardwareInfo, path: Path | None = None) -> Path:
        """Serialize `info` to JSON at /etc/hal0/hardware.json (or `path`).

        Uses atomic replace (tempfile + os.replace) so an interrupted write
        leaves the previous snapshot intact.
        """
        target = path or _paths.hardware_json()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(info.model_dump(mode="json"), indent=2, sort_keys=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            tmp.write_text(payload)
            os.replace(tmp, target)
        except OSError as exc:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise HardwareProbeError(
                "could not write hardware.json",
                {"path": str(target), "error": str(exc)},
            ) from exc
        return target


__all__ = [
    "GPUInfo",
    "HardwareInfo",
    "HardwareProbe",
    "HardwareProbeError",
    "NPUInfo",
]

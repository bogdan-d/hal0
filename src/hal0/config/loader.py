"""Config loaders — read and validate TOML files at startup.

All loaders return validated pydantic models.  A ValidationError at startup
means the user has a malformed config file; the error message includes the
field path (PLAN.md §5 Tier 1: "Typos in [slot] backend = vukan raise at
startup with the field path").

Atomic writes mirror hal0.config.env.write_env_atomic: write to a tmpfile
in the same directory, fsync, then os.replace().  If the process dies
mid-write the prior file is left intact.

Port target: haloai lib/config.py (420 lines).
See PLAN.md §3 and §5 Tier 1.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from hal0.errors import Hal0Error
from hal0.config import paths
from hal0.config.schema import (
    CURRENT_SCHEMA_VERSION,
    Hal0Config,
    HardwareInfo,
    ProvidersConfig,
    SlotConfig,
    UpstreamsConfig,
)

# ── Typed errors ──────────────────────────────────────────────────────────────


class ConfigError(Hal0Error):
    """Base class for config load/save errors."""

    code = "config.error"
    status = 500


class ConfigNotFound(ConfigError):
    """A required config file does not exist."""

    code = "config.not_found"
    status = 404


class ConfigParseError(ConfigError):
    """A config file is present but contains invalid TOML or fails validation."""

    code = "config.parse_error"
    status = 500


# ── Atomic TOML write ─────────────────────────────────────────────────────────


def write_toml_atomic(path: Path | str, data: dict[str, Any]) -> None:
    """Write a TOML file atomically.

    Mirrors hal0.config.env.write_env_atomic but for TOML payloads:
    write to a tempfile in the same directory, fsync, then os.replace().
    The rename is atomic on POSIX when src and dst share a mount; because
    the tempfile is created in the same directory, that invariant holds.

    Args:
        path: Destination path for the TOML file.
        data: Mapping that tomli_w.dump understands.

    Raises:
        OSError: If the directory cannot be created, disk full, or the
                 rename fails for a filesystem reason.
        TypeError: If data contains non-TOML-encodable values.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path: Path | None = None
    try:
        fd, tmp_str = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        tmp_path = Path(tmp_str)
        try:
            with os.fdopen(fd, "wb") as f:
                tomli_w.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            with contextlib.suppress(OSError):
                os.close(fd)
            raise
        os.replace(tmp_path, path)
        tmp_path = None  # rename succeeded; don't clean up in finally
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)


# ── TOML reader ───────────────────────────────────────────────────────────────


def _read_toml(path: Path) -> dict[str, Any]:
    """Read a TOML file and return its contents as a dict.

    Raises:
        ConfigNotFound: If the file does not exist.
        ConfigParseError: If the file cannot be parsed as TOML.
    """
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError as exc:
        raise ConfigNotFound(
            f"config file not found: {path}",
            details={"path": str(path)},
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigParseError(
            f"failed to parse TOML at {path}: {exc}",
            details={"path": str(path), "reason": str(exc)},
        ) from exc


# ── hal0.toml ─────────────────────────────────────────────────────────────────


def load_hal0_config(path: Path | None = None) -> Hal0Config:
    """Load and validate hal0.toml.

    Args:
        path: Override path.  If None, uses hal0.config.paths.hal0_toml().

    Returns:
        A validated Hal0Config.  If the file does not exist, returns the
        default config (all defaults, schema_version=CURRENT_SCHEMA_VERSION).

    Raises:
        ConfigParseError: If the TOML is malformed or fails validation.
    """
    target = path if path is not None else paths.hal0_toml()
    if not Path(target).exists():
        return Hal0Config()
    raw = _read_toml(Path(target))
    try:
        return Hal0Config.model_validate(raw)
    except Exception as exc:
        raise ConfigParseError(
            f"failed to validate hal0 config at {target}: {exc}",
            details={"path": str(target), "reason": str(exc)},
        ) from exc


def save_hal0_config(cfg: Hal0Config, path: Path | None = None) -> None:
    """Atomically write hal0.toml.

    Args:
        cfg: Validated Hal0Config to persist.
        path: Override path.  If None, uses hal0.config.paths.hal0_toml().
    """
    target = path if path is not None else paths.hal0_toml()
    data = cfg.model_dump(mode="python", exclude_none=False)
    write_toml_atomic(target, data)


# ── slots/<name>.toml ─────────────────────────────────────────────────────────


def load_slot_config(slot_name: str, path: Path | None = None) -> SlotConfig:
    """Load and validate /etc/hal0/slots/<slot_name>.toml.

    The on-disk shape (per haloai lib/config.py) nests fields under
    [slot], [model], etc.  We normalise that into the flat SlotConfig
    shape: [slot] keys hoist to the top level, [model] stays nested,
    everything else lands in ``extra``.

    Args:
        slot_name: e.g. "primary", "embed", "stt", "tts".
        path: Override path.  If None, uses
              hal0.config.paths.slots_config_dir() / f"{slot_name}.toml".

    Returns:
        A validated SlotConfig.

    Raises:
        ConfigNotFound: If the slot TOML doesn't exist.
        ConfigParseError: If the TOML is malformed or fails validation.
    """
    target = path if path is not None else paths.slots_config_dir() / f"{slot_name}.toml"
    raw = _read_toml(Path(target))
    flattened = _flatten_slot_toml(raw, slot_name=slot_name)
    try:
        return SlotConfig.model_validate(flattened)
    except Exception as exc:
        raise ConfigParseError(
            f"failed to validate slot config {slot_name!r} at {target}: {exc}",
            details={"path": str(target), "slot": slot_name, "reason": str(exc)},
        ) from exc


def save_slot_config(cfg: SlotConfig, path: Path | None = None) -> None:
    """Atomically write a slot config TOML.

    The pydantic SlotConfig is flat; we re-nest into the on-disk shape
    that haloai writes ([slot] / [model] sections) so hand-edits stay
    readable.

    Args:
        cfg: Validated SlotConfig to persist.
        path: Override path.  If None, derives from
              paths.slots_config_dir() / f"{cfg.name}.toml".
    """
    target = path if path is not None else paths.slots_config_dir() / f"{cfg.name}.toml"
    data = _unflatten_slot_toml(cfg)
    write_toml_atomic(target, data)


def list_slots() -> list[str]:
    """Return all configured slot names (stems of /etc/hal0/slots/*.toml)."""
    d = paths.slots_config_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.toml"))


# ── slot TOML shape helpers ──────────────────────────────────────────────────


def _flatten_slot_toml(raw: dict[str, Any], slot_name: str) -> dict[str, Any]:
    """Hoist [slot] keys to top-level so SlotConfig.model_validate works.

    The on-disk shape (haloai-compatible) is::

        [slot]
        name = "primary"
        port = 8081
        backend = "vulkan"

        [model]
        default = "qwen3-4b-q4_k_m"

        [defaults]
        threads = 12
        ...

    SlotConfig expects ``name`` and ``port`` at the top level, ``model``
    as a nested key, and stashes anything else under ``extra``.
    """
    slot_section = raw.get("slot", {}) if isinstance(raw, dict) else {}
    if not isinstance(slot_section, dict):
        slot_section = {}

    # Hoist [slot] keys; fall back to the on-disk filename for `name` if
    # the TOML omits it.
    out: dict[str, Any] = {**slot_section}
    out.setdefault("name", slot_name)

    # Nested [model] section.
    model_section = raw.get("model")
    if isinstance(model_section, dict):
        out["model"] = model_section

    # Anything else (e.g. [defaults], [server], custom sections) lands in
    # `extra` so we don't lose it on round-trip.
    extra: dict[str, Any] = {}
    for k, v in raw.items():
        if k in ("slot", "model"):
            continue
        extra[k] = v
    if extra:
        out["extra"] = extra

    return out


def _unflatten_slot_toml(cfg: SlotConfig) -> dict[str, Any]:
    """Inverse of _flatten_slot_toml — produce the on-disk shape."""
    data = cfg.model_dump(mode="python", exclude_none=False)
    out: dict[str, Any] = {
        "slot": {
            "name": data["name"],
            "port": data["port"],
            "backend": data["backend"],
            "provider": data["provider"],
            "enabled": data["enabled"],
            "workers": data["workers"],
            "idle_timeout_s": data["idle_timeout_s"],
        },
        "model": data["model"],
    }
    extra = data.get("extra") or {}
    if isinstance(extra, dict):
        for k, v in extra.items():
            # NOTE: keep user-authored sections (`[defaults]`, etc.) at
            # their original top-level position on round-trip.
            if k in ("slot", "model"):
                continue
            out[k] = v
    return out


# ── providers.toml ────────────────────────────────────────────────────────────


def load_providers_config(path: Path | None = None) -> ProvidersConfig:
    """Load and validate providers.toml.

    Returns an empty ProvidersConfig if the file does not exist.
    """
    target = path if path is not None else paths.etc() / "providers.toml"
    if not Path(target).exists():
        return ProvidersConfig()
    raw = _read_toml(Path(target))
    try:
        return ProvidersConfig.model_validate(raw)
    except Exception as exc:
        raise ConfigParseError(
            f"failed to validate providers.toml at {target}: {exc}",
            details={"path": str(target), "reason": str(exc)},
        ) from exc


def save_providers_config(cfg: ProvidersConfig, path: Path | None = None) -> None:
    """Atomically write providers.toml."""
    target = path if path is not None else paths.etc() / "providers.toml"
    write_toml_atomic(target, cfg.model_dump(mode="python"))


# ── upstreams.toml ────────────────────────────────────────────────────────────


def load_upstreams_config(path: Path | None = None) -> UpstreamsConfig:
    """Load and validate upstreams.toml.

    Returns an empty UpstreamsConfig if the file does not exist.
    """
    target = path if path is not None else paths.etc() / "upstreams.toml"
    if not Path(target).exists():
        return UpstreamsConfig()
    raw = _read_toml(Path(target))
    try:
        return UpstreamsConfig.model_validate(raw)
    except Exception as exc:
        raise ConfigParseError(
            f"failed to validate upstreams.toml at {target}: {exc}",
            details={"path": str(target), "reason": str(exc)},
        ) from exc


def save_upstreams_config(cfg: UpstreamsConfig, path: Path | None = None) -> None:
    """Atomically write upstreams.toml."""
    target = path if path is not None else paths.etc() / "upstreams.toml"
    write_toml_atomic(target, cfg.model_dump(mode="python"))


# ── hardware.json (JSON, not TOML) ────────────────────────────────────────────


def load_hardware_info(path: Path | None = None) -> HardwareInfo:
    """Load /etc/hal0/hardware.json and return a validated HardwareInfo.

    Returns the all-defaults HardwareInfo if the file is absent — the
    hardware module owns probing; callers that need real data should run
    `hal0 probe` first.

    Raises:
        ConfigParseError: If the JSON cannot be parsed or fails validation.
    """
    import json

    target = path if path is not None else paths.hardware_json()
    if not Path(target).exists():
        return HardwareInfo()
    try:
        raw = json.loads(Path(target).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigParseError(
            f"failed to parse hardware.json at {target}: {exc}",
            details={"path": str(target), "reason": str(exc)},
        ) from exc
    try:
        return HardwareInfo.model_validate(raw)
    except Exception as exc:
        raise ConfigParseError(
            f"failed to validate hardware.json at {target}: {exc}",
            details={"path": str(target), "reason": str(exc)},
        ) from exc


def save_hardware_info(info: HardwareInfo, path: Path | None = None) -> None:
    """Atomically write hardware.json.

    Uses the same tmpfile+fsync+rename pattern as write_toml_atomic, but
    against JSON (hardware.json is human-readable JSON per PLAN.md §2).
    """
    import json

    target = Path(path if path is not None else paths.hardware_json())
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(info.model_dump(mode="python"), indent=2, sort_keys=True) + "\n"

    tmp_path: Path | None = None
    try:
        fd, tmp_str = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        tmp_path = Path(tmp_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            with contextlib.suppress(OSError):
                os.close(fd)
            raise
        os.replace(tmp_path, target)
        tmp_path = None
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "ConfigError",
    "ConfigNotFound",
    "ConfigParseError",
    "list_slots",
    "load_hal0_config",
    "load_hardware_info",
    "load_providers_config",
    "load_slot_config",
    "load_upstreams_config",
    "save_hal0_config",
    "save_hardware_info",
    "save_providers_config",
    "save_slot_config",
    "save_upstreams_config",
    "write_toml_atomic",
]

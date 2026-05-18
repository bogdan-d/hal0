"""Pydantic models + atomic read/write for ``/etc/hal0/capabilities.toml``.

The overlay configuration carries one :class:`CapabilitySelection` per
(slot, child) tuple. The on-disk shape is intentionally flat / nested
TOML so operators can hand-edit the file::

    [selections.embed.embed]
    backend = "vulkan"
    provider = "llama-server"
    model   = "nomic-embed-text-v1.5"
    enabled = true

    [selections.voice.tts]
    backend = "vulkan"
    provider = "kokoro"
    model   = "kokoro-v1"
    enabled = false

The full file is rewritten atomically on every change via
:func:`hal0.config.loader.write_toml_atomic` so an interrupted write
leaves the prior file intact.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hal0.config import paths
from hal0.config.loader import write_toml_atomic


class CapabilitySelection(BaseModel):
    """One operator-facing selection for a (slot, child) tuple.

    Mirrors the dashboard's per-child editor card: which backend the
    user picked, which provider runs on that backend, which model id
    they bound, and whether the child is currently active.
    """

    model_config = {"populate_by_name": True, "str_strip_whitespace": True}

    backend: str = Field(
        default="",
        description="Backend id from the catalog: 'vulkan' | 'rocm' | 'npu' | 'cpu' | 'flm'.",
    )
    provider: str = Field(
        default="",
        description="Provider name: 'llama-server' | 'flm' | 'moonshine' | 'kokoro' | 'comfyui'.",
    )
    model: str = Field(
        default="",
        description="Model id from the registry. Empty when the child is unset.",
    )
    enabled: bool = Field(
        default=False,
        description="True when the underlying slot should be loaded with this model.",
    )


class CapabilityConfig(BaseModel):
    """Parsed ``/etc/hal0/capabilities.toml``.

    Selections are keyed ``[selections.<slot>.<child>]`` — see the module
    docstring for the on-disk shape. Empty selections are allowed (the
    orchestrator initialises them lazily on first read).
    """

    model_config = {"populate_by_name": True, "extra": "allow"}

    selections: dict[str, dict[str, CapabilitySelection]] = Field(
        default_factory=dict,
        description="Nested map: { slot_name: { child_name: CapabilitySelection } }.",
    )


# ── Path resolution ───────────────────────────────────────────────────────────


def capabilities_toml_path() -> Path:
    """Return ``/etc/hal0/capabilities.toml`` (HAL0_HOME-aware)."""
    return paths.etc() / "capabilities.toml"


# ── Read / write ──────────────────────────────────────────────────────────────


def load_capabilities_config(path: Path | None = None) -> CapabilityConfig:
    """Load and validate ``capabilities.toml``.

    Returns an empty :class:`CapabilityConfig` when the file does not
    exist — callers (notably :meth:`CapabilityOrchestrator.initialize_if_missing`)
    detect that with :func:`exists` below and seed defaults.
    """
    target = path if path is not None else capabilities_toml_path()
    if not Path(target).exists():
        return CapabilityConfig()
    with open(target, "rb") as f:
        raw = tomllib.load(f)
    return CapabilityConfig.model_validate(raw)


def save_capabilities_config(cfg: CapabilityConfig, path: Path | None = None) -> None:
    """Atomically rewrite ``capabilities.toml`` from a validated config."""
    target = path if path is not None else capabilities_toml_path()
    # Pydantic v2 ``model_dump`` walks the nested CapabilitySelection tables
    # into plain dicts — exactly the shape ``tomli_w.dump`` wants.
    data: dict[str, Any] = cfg.model_dump(mode="python")
    write_toml_atomic(target, data)


__all__ = [
    "CapabilityConfig",
    "CapabilitySelection",
    "capabilities_toml_path",
    "load_capabilities_config",
    "save_capabilities_config",
]

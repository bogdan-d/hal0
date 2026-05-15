"""Pydantic v2 schema models for hal0 configuration.

All TOML files under /etc/hal0/ are validated against these models at
startup.  Typos like backend = "vukan" raise a ValidationError with the
field path (PLAN.md §5 Tier 1).

Model hierarchy:
    Hal0Config       — top-level hal0.toml
      ProvidersConfig  — providers.toml (inline or separate)
      UpstreamsConfig  — upstreams.toml (inline or separate)
    SlotConfig       — slots/<name>.toml
    ModelConfig      — model fields within a slot config

Port target: haloai lib/config.py (420 lines).
See PLAN.md §3, §5 Tier 1 ("pydantic-validated TOML schema at load time").
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

# ── Shared ─────────────────────────────────────────────────────────────────────


_VALID_BACKENDS = frozenset({"vulkan", "rocm", "flm", "moonshine", "kokoro", "cpu"})


# ── SlotConfig ─────────────────────────────────────────────────────────────────


class ModelConfig(BaseModel):
    """[model] section in a slot TOML.

    Specifies which model the slot loads by default and any inference
    parameters that override the global defaults.
    """

    model_config = {"populate_by_name": True}

    default: str = Field(
        default="",
        description="Default model id from the registry.  Must exist in /var/lib/hal0/registry/.",
    )
    context_size: int = Field(
        default=4096,
        ge=128,
        description="Context window size in tokens.",
    )
    n_gpu_layers: int = Field(
        default=-1,
        description="Number of layers to offload to GPU.  -1 means all.",
    )
    rope_freq_base: float = Field(
        default=0.0,
        description="RoPE frequency base override.  0.0 means use model default.",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific model params passed verbatim to the backend.",
    )


class SlotConfig(BaseModel):
    """Pydantic model for a single slot's TOML config (slots/<name>.toml).

    Fields correspond to the [slot], [model], and [server] sections.
    See PLAN.md §2 (filesystem layout).
    """

    model_config = {"populate_by_name": True}

    # [slot] section
    name: str = Field(..., description="Slot name, e.g. 'primary'.")
    port: int = Field(
        ..., ge=8081, le=8099, description="Host port for this slot (127.0.0.1 only)."
    )
    backend: str = Field(
        default="vulkan",
        description="Backend type: 'vulkan' | 'rocm' | 'flm' | 'moonshine' | 'kokoro' | 'cpu'.",
    )
    provider: str = Field(
        default="llama-server",
        description="Provider name: 'llama-server' | 'flm' | 'moonshine' | 'kokoro'.",
    )
    enabled: bool = Field(default=True, description="Whether this slot is started on hal0 startup.")

    # [model] section (nested)
    model: ModelConfig = Field(default_factory=ModelConfig)

    # [server] section
    workers: int = Field(default=1, ge=1, description="Number of parallel request workers.")
    idle_timeout_s: int = Field(
        default=300,
        ge=0,
        description="Seconds idle before transitioning to 'idle' state.  0 disables.",
    )

    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific slot params passed verbatim.",
    )

    @field_validator("backend")
    @classmethod
    def backend_valid(cls, v: str) -> str:
        if v not in _VALID_BACKENDS:
            raise ValueError(f"backend {v!r} is not valid; choose from {sorted(_VALID_BACKENDS)}")
        return v


# ── ProvidersConfig ────────────────────────────────────────────────────────────


class ProviderEntry(BaseModel):
    """One [[provider]] entry in providers.toml."""

    model_config = {"populate_by_name": True}

    catalog_id: str = Field(
        ..., description="References an entry in upstreams.integrations._CATALOG."
    )
    name: str = Field(default="", description="User-visible name override.")
    base_url: str = Field(
        default="", description="URL override (leave empty to use catalog default)."
    )
    auth_value_env: str = Field(
        default="",
        description="Env var holding the API key.  Never stored in plain text.",
    )
    enabled: bool = Field(default=True)
    models: list[str] = Field(default_factory=list, description="User-selected model ids.")


class ProvidersConfig(BaseModel):
    """Parsed providers.toml."""

    model_config = {"populate_by_name": True}

    provider: list[ProviderEntry] = Field(default_factory=list)


# ── UpstreamsConfig ────────────────────────────────────────────────────────────


class UpstreamEntry(BaseModel):
    """One [[upstream]] entry in upstreams.toml."""

    model_config = {"populate_by_name": True}

    name: str = Field(..., description="Unique upstream name.")
    kind: str = Field(default="remote", description="'slot' | 'remote'.")
    url: str = Field(..., description="Base URL.")
    auth_style: str = Field(default="bearer")
    auth_value_env: str = Field(default="")
    timeout_seconds: float = Field(default=300.0)
    slot_name: str | None = Field(default=None)
    warmup_strategy: str = Field(default="none")
    advertise_models: bool = Field(default=True)


class UpstreamsConfig(BaseModel):
    """Parsed upstreams.toml."""

    model_config = {"populate_by_name": True}

    upstream: list[UpstreamEntry] = Field(default_factory=list)


# ── Hal0Config ─────────────────────────────────────────────────────────────────


class MetaConfig(BaseModel):
    """[meta] section in hal0.toml.  Tracks config schema version for migrations."""

    model_config = {"populate_by_name": True}

    schema_version: int = Field(
        default=1,
        description=(
            "Config schema version.  hal0 config migrate bumps this when applying "
            "versioned transforms.  See PLAN.md §5 Tier 3."
        ),
    )


class SlotsConfig(BaseModel):
    """[slots] section in hal0.toml.  Global slot policy."""

    model_config = {"populate_by_name": True}

    max_slots: int = Field(
        default=0,
        ge=0,
        description="Maximum concurrent slots.  0 means unlimited.",
    )
    port_range_start: int = Field(default=8081, description="First port in the slot pool.")
    port_range_end: int = Field(default=8099, description="Last port in the slot pool (inclusive).")


class DispatcherConfig(BaseModel):
    """[dispatcher] section in hal0.toml."""

    model_config = {"populate_by_name": True}

    prefetch_timeout_s: float = Field(
        default=8.0,
        description="Cold-cache prefetch timeout (PLAN.md §5 Tier 2).",
    )
    prefetch_parallel_cap: int = Field(
        default=4,
        ge=1,
        description="Max concurrent upstream parallel prefetches.",
    )


class TelemetryConfig(BaseModel):
    """[telemetry] section in hal0.toml."""

    model_config = {"populate_by_name": True}

    enabled: bool = Field(
        default=False,
        description="Opt-in anonymous telemetry.  Off by default.  See PLAN.md §14.",
    )
    channel: str = Field(default="stable", description="Update channel: 'stable' | 'nightly'.")


class Hal0Config(BaseModel):
    """Top-level hal0.toml pydantic model.

    Populated by hal0.config.loader.load_hal0_config() at startup.
    Unknown top-level keys are accepted and stored in 'extra' to allow
    forward compatibility with future schema versions.
    """

    model_config = {"populate_by_name": True, "extra": "allow"}

    meta: MetaConfig = Field(default_factory=MetaConfig)
    slots: SlotsConfig = Field(default_factory=SlotsConfig)
    dispatcher: DispatcherConfig = Field(default_factory=DispatcherConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)

"""Provider abstract base class.

A Provider encapsulates the logic for a single inference backend (llama.cpp,
FLM, Moonshine, Kokoro).  It is stateless: all configuration is passed
per-call via slot_cfg and model_info.  SlotManager calls build_env() and
start_cmd() to construct the systemd environment; it calls health() and
infer() to probe and forward requests.

Port target: haloai lib/providers/base.py.
See PLAN.md §3, ARCHITECTURE.md §Key boundaries ("Providers are stateless").

ContainerSpec captures everything needed to render a docker-run-based
systemd ExecStart line.  Frozen so Providers cannot accidentally share
mutable state across slots.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ContainerSpec:
    """Docker/podman run specification for a container-per-slot systemd unit.

    Carries everything SlotManager needs to render a docker run command
    inside the hal0-slot@.service template.

    Frozen for safety: Providers build a ContainerSpec per (slot, model)
    pair and hand it to SlotManager which renders the unit template.

    See ARCHITECTURE.md §Key boundaries and PLAN.md §2 (deployment model).
    """

    image: str
    """Fully-qualified toolbox image ref, e.g. ghcr.io/hal0-dev/hal0-toolbox-vulkan:v1."""

    command: list[str]
    """argv for the inference process inside the container."""

    env: dict[str, str] = field(default_factory=dict)
    """Environment variables injected via docker run --env."""

    mounts: list[tuple[str, str]] = field(default_factory=list)
    """(host_path, container_path) volume mounts."""

    devices: list[str] = field(default_factory=list)
    """Device paths to pass through, e.g. ["/dev/dri/renderD128"]."""

    cap_add: list[str] = field(default_factory=list)
    """Linux capabilities to add, e.g. ["SYS_PTRACE"]."""

    security_opt: list[str] = field(default_factory=list)
    """docker run --security-opt values."""

    group_add: list[str] = field(default_factory=list)
    """Supplementary group names or GIDs."""

    port: int = 0
    """Host port the container listens on (127.0.0.1 only)."""

    network_mode: str = "host"
    """Docker network mode.  "host" is the default for slot containers."""

    extra_args: list[str] = field(default_factory=list)
    """Escape hatch: additional docker run arguments appended verbatim."""


class Provider(ABC):
    """Abstract base for a hal0 inference backend.

    Concrete implementations: LlamaServerProvider, FLMProvider,
    MoonshineProvider, KokoroProvider.

    Each provider is instantiated once and reused across all slots that use
    that backend type.  Providers must not hold per-slot mutable state.
    """

    name: str = ""
    """Short backend identifier, e.g. "llama-server".  Used in slot configs
    and structured logs."""

    @abstractmethod
    def build_env(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> dict[str, str]:
        """Compute the EnvironmentFile contents for a slot.

        Returns a mapping of HAL0_* variable names to string values.
        Caller (SlotManager.spawn) writes the file atomically via
        hal0.config.env.write_env_atomic (PLAN.md §5 Tier 1).

        Args:
            slot_cfg:   Raw slot TOML dict (or SlotConfig model as dict).
            model_info: Model registry entry (id, path, size_bytes, …).
        """

    @abstractmethod
    def start_cmd(self, env: dict[str, str]) -> list[str]:
        """Return the argv list for spawning this backend outside systemd.

        Mirrors the systemd ExecStart.  Used by unit template rendering
        and integration tests.
        """

    @abstractmethod
    async def health(self, port: int) -> dict[str, Any]:
        """Run a health check against the backend on *port*.

        Returns {"ok": bool, "status": str, ...}.

        For llama-server and FLM: requires non-empty /v1/models plus a
        /v1/chat/completions with max_tokens=1 (PLAN.md §5 Tier 1 fix).
        """

    @abstractmethod
    async def infer(self, port: int, body: dict[str, Any]) -> dict[str, Any]:
        """Passthrough inference against the provider's OpenAI-compatible API.

        Thin wrapper; the Dispatcher is the primary request path — this is
        used for direct provider-level tests and CLI smoke checks.
        """

    @abstractmethod
    def container_spec(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> ContainerSpec:
        """Build the ContainerSpec for this slot + model combination.

        Called by SlotManager.spawn() to render the systemd unit override.
        """

    def image_ref(self, slot_cfg: dict[str, Any]) -> str:
        """Return the toolbox image reference for this Provider + slot config.

        Example: "ghcr.io/hal0-dev/hal0-toolbox-vulkan:v1".
        Varies by slot.backend (Vulkan vs ROCm for llama-server).
        Concrete Providers MUST override.

        Raises:
            NotImplementedError: Until Phase 1 per-provider implementation.
        """
        raise NotImplementedError(f"Phase 1: {type(self).__name__} must implement image_ref()")

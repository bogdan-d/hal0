"""Slot lifecycle manager.

SlotManager owns every aspect of slot lifecycle: spawn, terminate, load,
unload, restart, swap.  It talks to systemd via asyncio subprocesses, reads
and writes slot env files via hal0.config.env.write_env_atomic, and persists
state transitions to /var/lib/hal0/slots/<name>/state.json.

Port target: haloai lib/slots.py (1082 lines).
Refactored for the state machine defined in hal0.slots.state (PLAN.md §5 Tier 3).

See PLAN.md §3 (module port plan) and PLAN.md §5 (reliability work).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hal0.slots.state import SlotState

if TYPE_CHECKING:
    from hal0.config.schema import SlotConfig


class Slot:
    """Runtime handle for a single inference slot.

    Carries the slot name, current state, and any live metadata returned
    by the last health probe.  Immutable snapshot — SlotManager is the
    authoritative mutable source.
    """

    def __init__(
        self,
        name: str,
        state: SlotState = SlotState.OFFLINE,
        port: int = 0,
        model_id: str | None = None,
        backend: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.state = state
        self.port = port
        self.model_id = model_id
        self.backend = backend
        self.metadata: dict[str, Any] = metadata or {}

    def as_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict for API responses."""
        return {
            "name": self.name,
            "state": self.state.value,
            "port": self.port,
            "model_id": self.model_id,
            "backend": self.backend,
            "metadata": self.metadata,
        }


class SlotManager:
    """Manages the lifecycle of all hal0 inference slots.

    Each public method corresponds to a CLI subcommand and an API route.
    All methods are async so they can be awaited from FastAPI route handlers
    and from the Typer CLI via asyncio.run().

    Implementation note: Phase 1 ports from haloai lib/slots.py.  The
    state machine (hal0.slots.state) replaces the ad-hoc status strings
    in the original.
    """

    # ------------------------------------------------------------------ lifecycle

    async def load(self, slot_name: str, model_id: str | None = None) -> Slot:
        """Load a model into a slot.  Transitions: offline → (pulling →) starting → warming → ready.

        If model_id is None, uses the model assigned in the slot's TOML config.

        Raises: NotImplementedError until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/slots.py")

    async def unload(self, slot_name: str) -> Slot:
        """Gracefully unload a slot.  Transitions: (serving|idle|ready) → unloading → offline.

        Raises: NotImplementedError until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/slots.py")

    async def restart(self, slot_name: str) -> Slot:
        """Restart a running slot without changing its model assignment.

        Equivalent to unload followed by load, but faster for the caller.

        Raises: NotImplementedError until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/slots.py")

    async def swap(self, slot_name: str, new_model_id: str) -> Slot:
        """Hot-swap a slot's model.

        Stops the current inference process, rewrites the slot TOML, and
        restarts.  PLAN.md §5 Tier 2 notes the negative-tps clamp fix goes
        here.

        Raises: NotImplementedError until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/slots.py")

    # ------------------------------------------------------------------ queries

    async def status(self, slot_name: str) -> Slot:
        """Return a snapshot of the current slot state.

        Raises: NotImplementedError until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/slots.py")

    async def list(self) -> list[Slot]:
        """Return snapshots for all configured slots.

        Raises: NotImplementedError until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/slots.py")

    # ------------------------------------------------------------------ low-level

    async def spawn(self, slot_name: str, slot_cfg: SlotConfig) -> Slot:
        """Low-level: write env file and start the systemd unit.

        Called by load() after the model is confirmed present in the registry.
        Uses hal0.config.env.write_env_atomic (PLAN.md §5 Tier 1 fix).

        Raises: NotImplementedError until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/slots.py")

    async def terminate(self, slot_name: str, *, timeout_s: float = 30.0) -> None:
        """Low-level: issue systemctl stop and wait for the unit to exit.

        Raises: NotImplementedError until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/slots.py")

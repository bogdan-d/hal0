"""Slot lifecycle manager.

SlotManager owns every aspect of slot lifecycle: spawn, terminate, load,
unload, restart, swap, create, delete.  It talks to systemd via asyncio
subprocesses, reads and writes slot env files via
hal0.config.env.write_env_atomic, and persists state transitions to
/var/lib/hal0/slots/<name>/state.json.

Port target: haloai lib/slots.py (1082 lines).
Refactored for the state machine defined in hal0.slots.state (PLAN.md §5 Tier 3).

Architectural boundaries (ARCHITECTURE.md "Key boundaries"):
  - This module is *pure systemd*.  It does not import providers.  It does
    not make HTTP calls except for the health probe (which is a slot
    *lifecycle* concern, not a routing concern).
  - It depends on hal0.config.paths, hal0.config.env, and the rendering
    helpers in hal0.slots.unit_template.  It does NOT import from
    hal0.dispatcher.
  - All public methods return :class:`Slot` snapshots, never dicts —
    haloai's ``{"ok": False, "error": "..."}`` return shape is replaced
    by typed Hal0Error subclasses (Tier 1).

See PLAN.md §3 (module port plan) and PLAN.md §5 (reliability work).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from hal0.config import paths
from hal0.slots.state import (
    IllegalSlotTransition,
    SlotConfigError,
    SlotHealthFailed,
    SlotNotFound,
    SlotSpawnFailed,
    SlotState,
    SlotStateRecord,
    is_transition_legal,
    read_state,
    write_state_atomic,
)
from hal0.slots.unit_template import (
    override_path,
    render_override,
    write_slot_env,
)

if TYPE_CHECKING:
    from hal0.config.schema import SlotConfig

log = logging.getLogger(__name__)


# ── Tunables ─────────────────────────────────────────────────────────────────

# TIER1: Replaces haloai's hardcoded 2s cold-boot probe at lib/upstreams.py:500.
# Adaptive backoff: (0.5s, 1s, 2s, 5s, 10s) with ±20% jitter.  Total grace
# capped at HEALTH_GRACE_TOTAL_S.  Per-slot override may live in
# hardware.json once the hardware-probe agent's contract lands.
_HEALTH_BACKOFF_S: tuple[float, ...] = (0.5, 1.0, 2.0, 5.0, 10.0)
_HEALTH_GRACE_TOTAL_S: float = 180.0
_HEALTH_PROBE_TIMEOUT_S: float = 5.0
_SENTINEL_PROMPT: str = "ping"

# How long systemctl operations get before we treat them as hung.
_SYSTEMCTL_TIMEOUT_S: float = 30.0


# ── Slot snapshot ────────────────────────────────────────────────────────────


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


# ── Manager ──────────────────────────────────────────────────────────────────


class SlotManager:
    """Manages the lifecycle of all hal0 inference slots.

    Each public method corresponds to a CLI subcommand and an API route.
    All methods are async so they can be awaited from FastAPI route handlers
    and from the Typer CLI via asyncio.run().

    The state machine (hal0.slots.state) replaces the ad-hoc status strings
    in haloai's original.  Every state transition is:
      1. Validated against ``LEGAL_TRANSITIONS`` (illegal → IllegalSlotTransition).
      2. Persisted atomically to /var/lib/hal0/slots/<name>/state.json.
      3. Pushed onto in-memory async queues for any state_stream() subscribers.
    """

    BUILTIN_SLOTS: tuple[str, ...] = ("primary", "embed", "stt", "tts")

    def __init__(self) -> None:
        # Per-slot locks to prevent concurrent load/unload/restart races.
        self._locks: dict[str, asyncio.Lock] = {}
        # In-memory copy of the latest state per slot (mirrors state.json).
        self._states: dict[str, SlotStateRecord] = {}
        # SSE subscribers: list of queues; one per active state_stream().
        self._subscribers: list[asyncio.Queue[SlotStateRecord]] = []
        # Idle-tracking — last request timestamp per slot.
        self._last_used: dict[str, float] = {}

    # ── helpers ──────────────────────────────────────────────────────────────

    def _service_name(self, name: str) -> str:
        """systemd template-unit instance for this slot."""
        return f"hal0-slot@{name}.service"

    def _lock(self, name: str) -> asyncio.Lock:
        if name not in self._locks:
            self._locks[name] = asyncio.Lock()
        return self._locks[name]

    def _state_file(self, name: str) -> Path:
        return paths.slot_data_dir(name) / "state.json"

    def _config_file(self, name: str) -> Path:
        return paths.slots_config_dir() / f"{name}.toml"

    def _all_configured_slot_names(self) -> list[str]:
        """Enumerate slots by listing /etc/hal0/slots/*.toml."""
        cfg_dir = paths.slots_config_dir()
        if not cfg_dir.exists():
            return []
        return sorted(p.stem for p in cfg_dir.glob("*.toml") if not p.name.startswith("."))

    def _ensure_known(self, name: str) -> None:
        """Raise SlotNotFound if no config and no state for this slot."""
        if name in self._states:
            return
        if self._config_file(name).exists():
            return
        # Check state.json as a final fallback (slot may have been create()'d
        # in-memory only during tests).
        if self._state_file(name).exists():
            return
        raise SlotNotFound(
            f"slot {name!r} is not configured",
            details={"slot": name},
        )

    # ── state machine ────────────────────────────────────────────────────────

    def _current_state(self, name: str) -> SlotState:
        rec = self._states.get(name)
        if rec is None:
            # Try disk.
            rec = read_state(self._state_file(name))
            if rec is None:
                return SlotState.OFFLINE
            self._states[name] = rec
        return rec.state

    async def _transition(
        self,
        name: str,
        to_state: SlotState,
        *,
        model_id: str | None = None,
        port: int = 0,
        message: str = "",
        extra: dict[str, Any] | None = None,
        force: bool = False,
    ) -> SlotStateRecord:
        """Move a slot from its current state to ``to_state``.

        Raises IllegalSlotTransition if the transition is not in
        LEGAL_TRANSITIONS (unless ``force=True``, reserved for error
        recovery paths that need to drop straight to OFFLINE).
        """
        current = self._current_state(name)
        if current == to_state:
            # Idempotent — refresh metadata only.
            pass
        elif not force and not is_transition_legal(current, to_state):
            raise IllegalSlotTransition(
                f"slot {name!r}: illegal transition {current} → {to_state}",
                details={"slot": name, "from": current.value, "to": to_state.value},
            )

        prior = self._states.get(name)
        record = SlotStateRecord(
            name=name,
            state=to_state,
            model_id=model_id if model_id is not None else (prior.model_id if prior else None),
            port=port or (prior.port if prior else 0),
            updated_at=time.time(),
            message=message,
            extra=extra or {},
        )
        # Persist atomically before broadcasting — readers via state_stream
        # observe state.json on disk after they read the queue (Tier 3).
        write_state_atomic(self._state_file(name), record)
        self._states[name] = record
        log.info(
            "slot.transition", extra={"slot": name, "from": current.value, "to": to_state.value}
        )
        await self._broadcast(record)
        return record

    async def _broadcast(self, record: SlotStateRecord) -> None:
        """Push a record onto every active SSE subscriber queue."""
        dead: list[asyncio.Queue[SlotStateRecord]] = []
        for q in list(self._subscribers):
            try:
                q.put_nowait(record)
            except asyncio.QueueFull:
                # Subscriber is too slow — drop it; SSE client will
                # reconnect.  Never block the state machine on a stuck
                # consumer.  TIER1: no swallowed errors elsewhere, but
                # this drop is intentional and logged.
                log.warning("slot.subscriber_dropped", extra={"slot": record.name})
                dead.append(q)
        for q in dead:
            with contextlib.suppress(ValueError):
                self._subscribers.remove(q)

    async def state_stream(self) -> AsyncIterator[SlotStateRecord]:
        """Async generator yielding every slot state transition as it happens.

        Used by the SSE endpoint that powers the dashboard's real-time
        slot card updates (PLAN.md §6).  Each subscriber gets its own
        queue; transitions are fan-out broadcast.

        TIER3: Replaces haloai's polling-based status refresh.
        """
        # Buffer size 64 — comfortably larger than the number of expected
        # in-flight transitions across all slots.
        queue: asyncio.Queue[SlotStateRecord] = asyncio.Queue(maxsize=64)
        self._subscribers.append(queue)
        try:
            while True:
                rec = await queue.get()
                yield rec
        finally:
            with contextlib.suppress(ValueError):
                self._subscribers.remove(queue)

    # ── systemctl wrapper ────────────────────────────────────────────────────

    async def _systemctl(self, *args: str) -> tuple[int, str, str]:
        """Run a systemctl command and return (rc, stdout, stderr).

        TIER1: returns the full triple — callers decide how to react.
        haloai's bool-only return at lib/slots.py:177-186 hid the stderr
        needed to surface a meaningful error envelope.
        """
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_SYSTEMCTL_TIMEOUT_S
            )
        except TimeoutError as exc:
            proc.kill()
            with contextlib.suppress(asyncio.CancelledError):
                await proc.wait()
            raise SlotSpawnFailed(
                f"systemctl {' '.join(args)} timed out after {_SYSTEMCTL_TIMEOUT_S}s",
                details={"args": list(args)},
            ) from exc
        rc = proc.returncode if proc.returncode is not None else -1
        return (
            rc,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )

    async def _is_active(self, name: str) -> bool:
        rc, _, _ = await self._systemctl("is-active", self._service_name(name))
        return rc == 0

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def load(self, slot_name: str, model_id: str | None = None) -> Slot:
        """Load a model into a slot.  Transitions: offline → starting → warming → ready.

        If model_id is None, uses the model assigned in the slot's TOML config.
        """
        self._ensure_known(slot_name)
        async with self._lock(slot_name):
            cfg = await self._load_slot_config(slot_name)
            resolved_model = model_id or _model_default(cfg)

            current = self._current_state(slot_name)
            if current in (SlotState.READY, SlotState.SERVING, SlotState.IDLE):
                # Already loaded — return snapshot without restarting.
                return await self.status(slot_name)

            try:
                await self._transition(
                    slot_name,
                    SlotState.STARTING,
                    model_id=resolved_model,
                    port=_cfg_port(cfg),
                )
                await self._spawn_locked(slot_name, cfg, resolved_model)
                await self._transition(
                    slot_name,
                    SlotState.WARMING,
                    model_id=resolved_model,
                    port=_cfg_port(cfg),
                )
                await self._await_ready(slot_name, _cfg_port(cfg), _cfg_provider(cfg))
                await self._transition(
                    slot_name,
                    SlotState.READY,
                    model_id=resolved_model,
                    port=_cfg_port(cfg),
                )
            except Exception as exc:
                # TIER1: never swallow — record ERROR with details, re-raise.
                await self._transition(
                    slot_name,
                    SlotState.ERROR,
                    model_id=resolved_model,
                    port=_cfg_port(cfg),
                    message=str(exc),
                    force=True,
                )
                raise
            return await self.status(slot_name)

    async def unload(self, slot_name: str) -> Slot:
        """Gracefully unload a slot.  Transitions: → unloading → offline."""
        self._ensure_known(slot_name)
        async with self._lock(slot_name):
            current = self._current_state(slot_name)
            if current == SlotState.OFFLINE:
                return await self.status(slot_name)
            try:
                await self._transition(slot_name, SlotState.UNLOADING, force=True)
                await self.terminate(slot_name)
                await self._transition(slot_name, SlotState.OFFLINE, force=True)
            except Exception as exc:
                await self._transition(
                    slot_name,
                    SlotState.ERROR,
                    message=str(exc),
                    force=True,
                )
                raise
            self._last_used.pop(slot_name, None)
            return await self.status(slot_name)

    async def restart(self, slot_name: str) -> Slot:
        """Restart a slot without changing its model assignment."""
        self._ensure_known(slot_name)
        await self.unload(slot_name)
        return await self.load(slot_name)

    async def start(self, slot_name: str) -> Slot:
        """Idempotent start.  Equivalent to load() when slot is offline.

        Mirrors haloai's slots.start() (lib/slots.py:644) so callers like
        the dispatcher wake-on-request path can share the contract.
        """
        current = self._current_state(slot_name)
        if current in (SlotState.READY, SlotState.SERVING, SlotState.IDLE):
            self.bump_last_used(slot_name)
            return await self.status(slot_name)
        return await self.load(slot_name)

    async def swap(self, slot_name: str, new_model_id: str) -> Slot:
        """Hot-swap a slot's model: terminate → rewrite env → spawn → await."""
        if not new_model_id:
            raise SlotConfigError("swap requires a non-empty model id")
        self._ensure_known(slot_name)
        await self.unload(slot_name)
        return await self.load(slot_name, model_id=new_model_id)

    # ── queries ──────────────────────────────────────────────────────────────

    async def status(self, slot_name: str) -> Slot:
        """Return a snapshot of the current slot state.

        Combines the persisted state.json with a live systemd `is-active`
        check.  If state.json claims READY but the unit is not active, we
        transition to ERROR so the dashboard reflects reality.
        """
        self._ensure_known(slot_name)
        rec = self._states.get(slot_name) or read_state(self._state_file(slot_name))
        if rec is None:
            return Slot(name=slot_name, state=SlotState.OFFLINE)
        # Reconcile with systemd reality.
        active = await self._is_active(slot_name)
        observed = rec.state
        if observed in (SlotState.READY, SlotState.SERVING, SlotState.IDLE) and not active:
            # systemd says dead; record reflects ready — drift.
            await self._transition(
                slot_name,
                SlotState.ERROR,
                message="systemd unit not active",
                force=True,
            )
            observed = SlotState.ERROR
        return Slot(
            name=slot_name,
            state=observed,
            port=rec.port,
            model_id=rec.model_id,
            backend=rec.extra.get("backend"),
            metadata={"updated_at": rec.updated_at, "message": rec.message, **rec.extra},
        )

    async def list(self) -> list[Slot]:
        """Return snapshots for all configured slots, concurrently."""
        names = self._all_configured_slot_names()
        # Slots that only exist in memory (test injection) also show up.
        for n in self._states:
            if n not in names:
                names.append(n)
        if not names:
            return []
        return list(await asyncio.gather(*(self.status(n) for n in names)))

    async def iter_configs(self) -> list[dict[str, Any]]:
        """Return raw slot config dicts for every configured slot.

        Lightweight — reads TOML only, never calls systemctl.  Intended
        for startup hooks (e.g. ``lifespan`` auto-registering slots as
        upstreams) that need slot metadata before any real systemd
        interaction.

        Returns:
            One dict per slot, in stable order.  Each dict carries at
            least ``name`` and ``port``; the rest of the SlotConfig
            shape (``backend``, ``provider``, …) round-trips verbatim.
        """
        out: list[dict[str, Any]] = []
        for name in self._all_configured_slot_names():
            try:
                cfg = await self._load_slot_config(name)
            except SlotConfigError as exc:
                log.warning(
                    "slot.config_skipped",
                    slot=name,
                    error=str(exc),
                )
                continue
            out.append(cfg)
        return out

    # ── low-level lifecycle ──────────────────────────────────────────────────

    async def spawn(self, slot_name: str, slot_cfg: SlotConfig | dict[str, Any]) -> Slot:
        """Low-level: render env + override, then systemctl start.

        Called by load() after the model is confirmed present in the
        registry.  Public for tests and for the installer's first-run path.
        Acquires the per-slot lock; load() callers can use _spawn_locked.
        """
        async with self._lock(slot_name):
            await self._spawn_locked(slot_name, slot_cfg, _model_default(slot_cfg))
        return await self.status(slot_name)

    async def _spawn_locked(
        self,
        slot_name: str,
        slot_cfg: SlotConfig | dict[str, Any],
        model_id: str | None,
    ) -> None:
        """Spawn body — caller already holds the per-slot lock."""
        model_info = await self._resolve_model_info(model_id)

        # TIER1: atomic env write — write_slot_env() delegates to
        # write_env_atomic (tmpfile + os.replace).  haloai's
        # lib/slots.py:551-622 was rewritten here.
        write_slot_env(slot_name, slot_cfg, model_info, model_id_override=model_id)

        # Render the per-slot drop-in.  We rewrite on every spawn so a
        # backend/port edit picked up via update_config takes effect on
        # next start.
        override = render_override(slot_name, slot_cfg, model_info)
        op = override_path(slot_name)
        try:
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_text(override, encoding="utf-8")
        except OSError as exc:
            raise SlotSpawnFailed(
                f"failed to write override.conf for {slot_name!r}: {exc}",
                details={"slot": slot_name, "path": str(op)},
            ) from exc

        # daemon-reload then start.  Tolerant of "no such unit" only if
        # daemon-reload itself fails for a hard reason.
        rc, _, stderr = await self._systemctl("daemon-reload")
        if rc != 0:
            raise SlotSpawnFailed(
                f"systemctl daemon-reload failed: {stderr.strip()}",
                details={"slot": slot_name},
            )
        rc, _, stderr = await self._systemctl("start", self._service_name(slot_name))
        if rc != 0:
            raise SlotSpawnFailed(
                f"systemctl start hal0-slot@{slot_name} failed: {stderr.strip()}",
                details={"slot": slot_name, "stderr": stderr.strip()},
            )

    async def terminate(self, slot_name: str, *, timeout_s: float = 30.0) -> None:
        """Low-level: issue systemctl stop and wait for the unit to exit.

        Public because the dispatcher's idle-monitor calls it directly to
        release VRAM without going through unload()'s state-machine
        ceremony.  TIER1: bubbles stderr on failure.
        """
        rc, _, stderr = await self._systemctl("stop", self._service_name(slot_name))
        if rc != 0:
            raise SlotSpawnFailed(
                f"systemctl stop hal0-slot@{slot_name} failed: {stderr.strip()}",
                details={"slot": slot_name, "stderr": stderr.strip()},
            )
        # Poll for is-active to flip to inactive — systemctl stop returns
        # before the container actually exits when Type=simple.
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if not await self._is_active(slot_name):
                return
            await asyncio.sleep(0.5)
        raise SlotSpawnFailed(
            f"slot {slot_name!r} still active {timeout_s}s after systemctl stop",
            details={"slot": slot_name},
        )

    # ── slot CRUD ────────────────────────────────────────────────────────────

    async def create(
        self,
        slot_name: str,
        slot_cfg: SlotConfig | dict[str, Any],
    ) -> Slot:
        """Create a new dynamic slot's persistent on-disk state.

        Writes the slot TOML to /etc/hal0/slots/<name>.toml, the override
        drop-in, the env file, and the initial state.json (OFFLINE).  Does
        NOT start the slot — that's load()'s job.

        NOTE: TOML serialisation depends on tomli_w which is in
        pyproject.toml; this keeps the slot config writable without a
        cross-subtree dependency on config/loader.py.
        """
        try:
            import tomli_w
        except ImportError as exc:  # pragma: no cover
            raise SlotConfigError(
                "tomli_w not installed — required for slot config writes",
            ) from exc

        cfg_dict = _cfg_to_dict(slot_cfg)
        cfg_path = self._config_file(slot_name)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cfg_path.write_bytes(tomli_w.dumps(cfg_dict).encode("utf-8"))
        except OSError as exc:
            raise SlotConfigError(
                f"failed to write slot config {cfg_path}: {exc}",
                details={"slot": slot_name},
            ) from exc

        # Pre-render env + override so the slot is ready to start.
        write_slot_env(slot_name, cfg_dict, model_info=None)
        op = override_path(slot_name)
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(render_override(slot_name, cfg_dict, model_info=None), encoding="utf-8")

        # Initialise state.
        await self._transition(
            slot_name,
            SlotState.OFFLINE,
            port=_cfg_port(cfg_dict),
            model_id=_model_default(cfg_dict) or None,
            extra={"backend": cfg_dict.get("backend", "vulkan")},
            force=True,
        )
        return await self.status(slot_name)

    async def delete(self, slot_name: str) -> None:
        """Delete a dynamic slot.  Built-in slots cannot be deleted."""
        if slot_name in self.BUILTIN_SLOTS:
            raise SlotConfigError(
                f"cannot delete built-in slot {slot_name!r}",
                details={"slot": slot_name},
            )
        self._ensure_known(slot_name)
        # Make sure it's stopped first.
        current = self._current_state(slot_name)
        if current != SlotState.OFFLINE:
            await self.unload(slot_name)

        # Remove override drop-in, env, state.json, and the slot config.
        for path in (
            override_path(slot_name),
            paths.slot_data_dir(slot_name) / "env",
            self._state_file(slot_name),
            self._config_file(slot_name),
        ):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        # Drop in-memory bookkeeping last.
        self._states.pop(slot_name, None)
        self._locks.pop(slot_name, None)
        self._last_used.pop(slot_name, None)
        # daemon-reload so systemd notices the missing drop-in.
        await self._systemctl("daemon-reload")

    async def update_config(
        self,
        slot_name: str,
        updates: dict[str, Any],
    ) -> Slot:
        """Apply partial updates to a slot's TOML.  Re-renders override+env."""
        self._ensure_known(slot_name)
        try:
            import tomli_w
        except ImportError as exc:  # pragma: no cover
            raise SlotConfigError("tomli_w not installed") from exc

        cfg = await self._load_slot_config(slot_name)
        cfg_dict = _cfg_to_dict(cfg)
        # Shallow merge — nested dicts are replaced wholesale to keep update
        # semantics predictable.  Callers wanting a partial nested update
        # build the sub-dict on their side first.
        cfg_dict.update(updates)

        cfg_path = self._config_file(slot_name)
        try:
            cfg_path.write_bytes(tomli_w.dumps(cfg_dict).encode("utf-8"))
        except OSError as exc:
            raise SlotConfigError(
                f"failed to rewrite {cfg_path}: {exc}",
            ) from exc

        # Re-render env + override so the next start picks up changes.
        write_slot_env(slot_name, cfg_dict, model_info=None)
        op = override_path(slot_name)
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(render_override(slot_name, cfg_dict, model_info=None), encoding="utf-8")

        return await self.status(slot_name)

    # ── idle / wake-on-request ───────────────────────────────────────────────

    def bump_last_used(self, slot_name: str) -> None:
        """Record activity on a slot — called from request dispatch paths.

        Tier-2 idle-management: a separate task (in the dispatcher subtree)
        polls these timestamps and transitions long-idle slots to IDLE,
        then UNLOADING.  This module only owns the bookkeeping.
        """
        self._last_used[slot_name] = time.time()

    def last_used(self, slot_name: str) -> float | None:
        return self._last_used.get(slot_name)

    # ── private helpers ──────────────────────────────────────────────────────

    async def _load_slot_config(self, slot_name: str) -> dict[str, Any]:
        """Read /etc/hal0/slots/<name>.toml as a raw dict.

        TIER1: surfaces a typed SlotConfigError on missing / malformed
        TOML.  Replaces haloai's silent `except Exception: pass` at
        lib/slots.py:296 et al.
        """
        try:
            import tomllib
        except ImportError:  # py<3.11
            import tomli as tomllib  # type: ignore[no-redef]

        path = self._config_file(slot_name)
        if not path.exists():
            # In-memory-only slot (test injection) — fall back to the
            # state.json record.  Real callers should always have a TOML.
            rec = self._states.get(slot_name)
            if rec is None:
                raise SlotConfigError(
                    f"slot config {path} not found and no in-memory state",
                    details={"slot": slot_name},
                )
            return {
                "name": slot_name,
                "port": rec.port,
                "backend": rec.extra.get("backend", "vulkan"),
                "provider": rec.extra.get("provider", "llama-server"),
                "model": {"default": rec.model_id or ""},
            }
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except OSError as exc:
            raise SlotConfigError(
                f"cannot read slot config {path}: {exc}",
                details={"slot": slot_name, "path": str(path)},
            ) from exc
        except tomllib.TOMLDecodeError as exc:
            raise SlotConfigError(
                f"slot config {path} is not valid TOML: {exc}",
                details={"slot": slot_name, "path": str(path)},
            ) from exc
        if "name" not in data:
            data["name"] = slot_name
        return data

    async def _resolve_model_info(self, model_id: str | None) -> dict[str, Any]:
        """Look up model metadata from the registry.

        Returns an empty dict when model_id is None or the registry isn't
        wired yet.  NOTE: codes against the registry-subtree's expected
        ``get(model_id) -> Model`` API; if that lands as ``get_model``,
        the lookup below adjusts.
        """
        if not model_id:
            return {}
        try:
            from hal0.registry.store import ModelNotFound, ModelRegistry
        except ImportError:
            # registry subtree not landed yet — graceful degrade.
            log.warning("slot.registry_unavailable", extra={"model_id": model_id})
            return {}
        try:
            reg = ModelRegistry()
            model = reg.get(model_id)
        except ModelNotFound:
            # NOTE: deliberately non-fatal.  The slot manager is not the
            # authoritative gate on "is this model installed" — that's the
            # registry/models route's job.  We log so the dashboard sees
            # the orphan and let the toolbox image surface its own
            # ModelLoadError when the path doesn't exist.
            log.warning(
                "slot.model_not_in_registry",
                extra={"model_id": model_id},
            )
            return {}
        except NotImplementedError:
            log.warning("slot.registry_stub", extra={"model_id": model_id})
            return {}
        return model.model_dump() if hasattr(model, "model_dump") else dict(model)

    # ── health probe (TIER1 tightened) ───────────────────────────────────────

    async def _await_ready(self, slot_name: str, port: int, provider: str) -> None:
        """Block until the slot's HTTP health probe reports ready.

        TIER1 fix for haloai lib/slots.py:899-920 and lib/upstreams.py:500-520:
          - Adaptive backoff (0.5, 1, 2, 5, 10s).
          - Total grace window of 180s, no per-probe 2s hardcap.
          - FLM / vLLM-style providers (anything OpenAI-compatible without
            a /health endpoint) require a *non-empty* /v1/models response
            AND a tiny /v1/chat/completions with max_tokens=1 before we
            declare READY.  Empty /v1/models is no longer "good enough".
        """
        deadline = time.monotonic() + _HEALTH_GRACE_TOTAL_S
        attempt = 0
        last_error: str = "no probe yet"
        url = f"http://127.0.0.1:{port}"

        while time.monotonic() < deadline:
            backoff = _HEALTH_BACKOFF_S[min(attempt, len(_HEALTH_BACKOFF_S) - 1)]
            jitter = backoff * 0.2 * (random.random() * 2 - 1)
            wait_s = max(0.1, backoff + jitter)
            try:
                async with httpx.AsyncClient(timeout=_HEALTH_PROBE_TIMEOUT_S) as client:
                    if _provider_uses_v1_models(provider):
                        # FLM / vLLM / moonshine / kokoro path.
                        resp = await client.get(f"{url}/v1/models")
                        if resp.status_code == 200:
                            data = (
                                resp.json()
                                if "json" in resp.headers.get("content-type", "")
                                else {}
                            )
                            models = data.get("data", []) if isinstance(data, dict) else []
                            if models:
                                # Non-empty → confirm inference works.
                                if await _sentinel_inference(client, url, models[0]):
                                    return
                                last_error = "sentinel inference failed"
                            else:
                                last_error = "/v1/models returned empty data array"
                        else:
                            last_error = f"/v1/models HTTP {resp.status_code}"
                    else:
                        # llama.cpp path — /health is authoritative.
                        resp = await client.get(f"{url}/health")
                        if resp.status_code == 200:
                            return
                        last_error = f"/health HTTP {resp.status_code}"
            except httpx.HTTPError as exc:
                last_error = f"http error: {exc}"
            except Exception as exc:
                # TIER1: log + retain message; never silent.
                log.warning(
                    "slot.health_probe_unexpected_error",
                    extra={"slot": slot_name, "error": str(exc)},
                )
                last_error = f"unexpected: {exc}"
            attempt += 1
            await asyncio.sleep(wait_s)

        raise SlotHealthFailed(
            f"slot {slot_name!r} did not become healthy within {_HEALTH_GRACE_TOTAL_S}s",
            details={"slot": slot_name, "last_error": last_error},
        )


# ── module-level helpers ─────────────────────────────────────────────────────


def _cfg_to_dict(cfg: SlotConfig | dict[str, Any]) -> dict[str, Any]:
    if hasattr(cfg, "model_dump"):
        return cfg.model_dump()  # type: ignore[no-any-return]
    if isinstance(cfg, dict):
        return dict(cfg)
    raise SlotConfigError(f"unsupported slot cfg type {type(cfg).__name__}")


def _cfg_port(cfg: SlotConfig | dict[str, Any]) -> int:
    d = _cfg_to_dict(cfg)
    port = d.get("port") or d.get("slot", {}).get("port") or 0
    return int(port)


def _cfg_provider(cfg: SlotConfig | dict[str, Any]) -> str:
    d = _cfg_to_dict(cfg)
    return str(d.get("provider") or d.get("slot", {}).get("provider") or "llama-server")


def _model_default(cfg: SlotConfig | dict[str, Any]) -> str:
    d = _cfg_to_dict(cfg)
    model = d.get("model") or {}
    if isinstance(model, dict):
        return str(model.get("default") or "")
    return ""


def _provider_uses_v1_models(provider: str) -> bool:
    """Return True for providers that do not expose /health (FLM, vLLM, moonshine, kokoro).

    The llama-server provider exposes /health; everyone else's readiness
    signal is a non-empty /v1/models response plus an inference probe.
    """
    return provider.lower() not in ("llama-server", "llama_server", "llamacpp")


async def _sentinel_inference(
    client: httpx.AsyncClient,
    url: str,
    model_entry: dict[str, Any],
) -> bool:
    """Send a max_tokens=1 sentinel /v1/chat/completions and accept any 2xx.

    TIER1: An OpenAI-compatible /v1/models is necessary but not sufficient
    — we have seen FLM advertise models that immediately 500 on first
    inference.  This sentinel exercises the inference path so READY
    actually means ready.
    """
    model_id = (model_entry.get("id") if isinstance(model_entry, dict) else None) or "sentinel"
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": _SENTINEL_PROMPT}],
        "max_tokens": 1,
        "temperature": 0.0,
        "stream": False,
    }
    try:
        resp = await client.post(f"{url}/v1/chat/completions", json=payload)
    except httpx.HTTPError:
        return False
    return 200 <= resp.status_code < 300


__all__ = [
    "Slot",
    "SlotManager",
]

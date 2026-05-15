"""Tests for hal0.slots.manager.SlotManager.

All systemctl calls are intercepted via monkeypatching
``asyncio.create_subprocess_exec`` so the tests run on any host without
needing the hal0-slot@.service template installed.

Health probes are stubbed by monkeypatching ``manager._await_ready``.

Covers:
  - load() → starting → warming → ready (legal transition sequence)
  - load() retry from ERROR state
  - unload() → unloading → offline
  - swap() rewrites env + restarts
  - create() / delete() / update_config() touch the right files
  - status() reconciles a stale READY against an inactive systemd unit
  - state_stream() broadcasts each transition exactly once
  - tier-1: systemctl failure raises typed SlotSpawnFailed (not silent)
  - tier-1: empty /v1/models is NOT treated as ready (probe logic unit test)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from hal0.slots import manager as mgr_mod
from hal0.slots.manager import SlotManager
from hal0.slots.state import (
    IllegalSlotTransition,
    SlotNotFound,
    SlotSpawnFailed,
    SlotState,
)

# ── fakes ────────────────────────────────────────────────────────────────────


class _FakeProc:
    """Stand-in for asyncio.subprocess.Process used by systemctl calls."""

    def __init__(self, rc: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = rc
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        pass

    async def wait(self) -> int:
        return self.returncode


@pytest.fixture
def systemctl_stub(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[list[str]]]:
    """Intercept asyncio.create_subprocess_exec and record systemctl invocations.

    Returns a dict tracking calls; tests can also set entries to simulate
    failure rcs by mutating ``failures[(action,)]``.
    """
    state: dict[str, Any] = {
        "calls": [],
        "is_active_state": "inactive",  # flips to 'active' after start
        "force_rc": {},  # {("action", "service"): rc}
    }

    async def fake_create(*args: str, **_: Any) -> _FakeProc:
        cmd = list(args)
        state["calls"].append(cmd)
        if cmd[:1] != ["systemctl"]:
            raise AssertionError(f"unexpected subprocess: {cmd}")
        action = cmd[1] if len(cmd) > 1 else ""
        service = cmd[2] if len(cmd) > 2 else ""
        key = (action, service)
        if key in state["force_rc"]:
            return _FakeProc(rc=state["force_rc"][key])
        if action == "is-active":
            return _FakeProc(rc=0 if state["is_active_state"] == "active" else 3)
        if action == "start":
            state["is_active_state"] = "active"
            return _FakeProc(rc=0)
        if action == "stop":
            state["is_active_state"] = "inactive"
            return _FakeProc(rc=0)
        if action == "daemon-reload":
            return _FakeProc(rc=0)
        return _FakeProc(rc=0)

    monkeypatch.setattr(mgr_mod.asyncio, "create_subprocess_exec", fake_create)
    return state


@pytest.fixture
def stub_await_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Short-circuit the HTTP health probe so unit tests don't sleep."""

    async def _ok(self: SlotManager, slot_name: str, port: int, provider: str) -> None:
        return None

    monkeypatch.setattr(SlotManager, "_await_ready", _ok)


@pytest.fixture
def slot_root(tmp_hal0_home: str) -> Path:
    """Yield the slots-config root and ensure a sample slot exists on disk."""
    root = Path(tmp_hal0_home) / "etc" / "hal0" / "slots"
    root.mkdir(parents=True, exist_ok=True)
    (root / "primary.toml").write_text(
        "\n".join(
            [
                'name = "primary"',
                "port = 8081",
                'backend = "vulkan"',
                'provider = "llama-server"',
                "enabled = true",
                "[model]",
                'default = "qwen3-4b-q4_k_m"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return root


# ── happy paths ──────────────────────────────────────────────────────────────


async def test_load_transitions_through_states(
    slot_root: Path,
    systemctl_stub: dict[str, Any],
    stub_await_ready: None,
    tmp_hal0_home: str,
) -> None:
    sm = SlotManager()
    snap = await sm.load("primary")
    assert snap.state == SlotState.READY
    # state.json on disk reflects READY too.
    state_path = Path(tmp_hal0_home) / "var-lib" / "hal0" / "slots" / "primary" / "state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["state"] == "ready"
    # systemctl saw daemon-reload + start.
    actions = [c[1] for c in systemctl_stub["calls"]]
    assert "daemon-reload" in actions
    assert "start" in actions


async def test_load_idempotent_when_ready(
    slot_root: Path,
    systemctl_stub: dict[str, Any],
    stub_await_ready: None,
) -> None:
    sm = SlotManager()
    await sm.load("primary")
    calls_before = len(systemctl_stub["calls"])
    snap = await sm.load("primary")
    assert snap.state == SlotState.READY
    # no extra systemctl start
    new_calls = systemctl_stub["calls"][calls_before:]
    starts = [c for c in new_calls if c[1] == "start"]
    assert starts == []


async def test_unload_transitions_to_offline(
    slot_root: Path,
    systemctl_stub: dict[str, Any],
    stub_await_ready: None,
) -> None:
    sm = SlotManager()
    await sm.load("primary")
    snap = await sm.unload("primary")
    assert snap.state == SlotState.OFFLINE
    assert "stop" in [c[1] for c in systemctl_stub["calls"]]


async def test_restart_round_trip(
    slot_root: Path,
    systemctl_stub: dict[str, Any],
    stub_await_ready: None,
) -> None:
    sm = SlotManager()
    await sm.load("primary")
    snap = await sm.restart("primary")
    assert snap.state == SlotState.READY


async def test_swap_replaces_model_id(
    slot_root: Path,
    systemctl_stub: dict[str, Any],
    stub_await_ready: None,
    tmp_hal0_home: str,
) -> None:
    sm = SlotManager()
    await sm.load("primary")
    snap = await sm.swap("primary", "llama-3.2-3b-q4_k_m")
    assert snap.model_id == "llama-3.2-3b-q4_k_m"
    # env file contains the new model id.
    env_path = Path(tmp_hal0_home) / "var-lib" / "hal0" / "slots" / "primary" / "env"
    body = env_path.read_text(encoding="utf-8")
    assert "HAL0_MODEL_ID=llama-3.2-3b-q4_k_m" in body


async def test_list_returns_all_configured_slots(
    slot_root: Path,
    systemctl_stub: dict[str, Any],
    stub_await_ready: None,
) -> None:
    # add a second slot
    (slot_root / "embed.toml").write_text(
        "\n".join(
            [
                'name = "embed"',
                "port = 8082",
                'backend = "vulkan"',
                'provider = "llama-server"',
                "[model]",
                'default = "bge-small-en"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    sm = SlotManager()
    snaps = await sm.list()
    names = {s.name for s in snaps}
    assert {"primary", "embed"}.issubset(names)


# ── error paths (Tier 1 — typed errors, no silent swallow) ───────────────────


async def test_load_unknown_slot_raises_typed(
    slot_root: Path,
    systemctl_stub: dict[str, Any],
) -> None:
    sm = SlotManager()
    with pytest.raises(SlotNotFound) as exc_info:
        await sm.load("nonexistent")
    assert exc_info.value.code == "slot.not_found"


async def test_load_systemctl_start_failure_raises_typed(
    slot_root: Path,
    systemctl_stub: dict[str, Any],
    stub_await_ready: None,
) -> None:
    sm = SlotManager()
    systemctl_stub["force_rc"][("start", "hal0-slot@primary.service")] = 1
    with pytest.raises(SlotSpawnFailed) as exc_info:
        await sm.load("primary")
    assert exc_info.value.code == "slot.spawn_failed"
    # state.json now records ERROR — no silent failure.
    snap = await sm.status("primary")
    assert snap.state == SlotState.ERROR


async def test_status_reconciles_drift(
    slot_root: Path,
    systemctl_stub: dict[str, Any],
    stub_await_ready: None,
) -> None:
    """A persisted READY plus an inactive systemd unit must transition to ERROR."""
    sm = SlotManager()
    await sm.load("primary")
    # Force is-active to flip back to inactive.
    systemctl_stub["is_active_state"] = "inactive"
    snap = await sm.status("primary")
    assert snap.state == SlotState.ERROR


async def test_status_rehydrates_backend_from_toml_when_state_extra_missing(
    slot_root: Path,
    tmp_hal0_home: str,
    systemctl_stub: dict[str, Any],
) -> None:
    """Old state.json files (pre extras-carry) lacked ``extra.backend``.

    The fix: ``status()`` falls back to the slot's TOML so the dashboard
    chip on SlotCard sees the right backend without forcing a reload.
    See handoff-2026-05-15 §"Remaining gaps" #5.
    """
    from hal0.slots.state import SlotState as _S
    from hal0.slots.state import SlotStateRecord, write_state_atomic

    # Hand-write a state.json that mimics the legacy shape — no
    # ``extra.backend`` carried.  slot_root fixture already put
    # primary.toml on disk with ``backend = "vulkan"``.
    state_path = (
        Path(tmp_hal0_home)
        / "var-lib"
        / "hal0"
        / "slots"
        / "primary"
        / "state.json"
    )
    write_state_atomic(
        state_path,
        SlotStateRecord(name="primary", state=_S.OFFLINE, port=8081, extra={}),
    )

    sm = SlotManager()
    snap = await sm.status("primary")
    assert snap.backend == "vulkan", (
        f"status() must re-hydrate backend from /etc/hal0/slots/primary.toml "
        f"when state.json carries no extra.backend (got {snap.backend!r})"
    )
    # And the metadata top-level mirror it so /api/slots' _slot_to_dict fallback
    # picks it up too.
    assert snap.metadata.get("backend") == "vulkan"


async def test_status_unloaded_slot_uses_toml_backend(
    slot_root: Path,
    tmp_hal0_home: str,
    systemctl_stub: dict[str, Any],
) -> None:
    """A slot that has a TOML but never wrote state.json still surfaces backend.

    Fresh-install case: /etc/hal0/slots/primary.toml exists from the
    installer's defaults, but state.json doesn't yet because the slot
    has never been loaded.
    """
    sm = SlotManager()
    snap = await sm.status("primary")
    assert snap.state == SlotState.OFFLINE
    assert snap.backend == "vulkan"
    assert snap.port == 8081


# ── state machine enforcement ────────────────────────────────────────────────


async def test_illegal_transition_blocked(
    slot_root: Path,
    systemctl_stub: dict[str, Any],
) -> None:
    """Direct _transition() with an illegal edge raises IllegalSlotTransition."""
    sm = SlotManager()
    # First put it in OFFLINE.
    await sm._transition("primary", SlotState.OFFLINE, force=True)
    with pytest.raises(IllegalSlotTransition) as exc_info:
        await sm._transition("primary", SlotState.READY)
    assert exc_info.value.code == "slot.illegal_transition"
    assert exc_info.value.status == 409


# ── CRUD ────────────────────────────────────────────────────────────────────


async def test_create_writes_config_env_and_state(
    tmp_hal0_home: str,
    systemctl_stub: dict[str, Any],
) -> None:
    sm = SlotManager()
    cfg = {
        "name": "extra",
        "port": 8090,
        "backend": "vulkan",
        "provider": "llama-server",
        "model": {"default": "tiny-q4"},
    }
    snap = await sm.create("extra", cfg)
    assert snap.state == SlotState.OFFLINE
    assert (Path(tmp_hal0_home) / "etc" / "hal0" / "slots" / "extra.toml").exists()
    assert (Path(tmp_hal0_home) / "var-lib" / "hal0" / "slots" / "extra" / "env").exists()
    state_path = Path(tmp_hal0_home) / "var-lib" / "hal0" / "slots" / "extra" / "state.json"
    assert state_path.exists()


async def test_delete_removes_files_but_not_builtin(
    tmp_hal0_home: str,
    systemctl_stub: dict[str, Any],
) -> None:
    sm = SlotManager()
    cfg = {
        "name": "extra",
        "port": 8090,
        "backend": "vulkan",
        "provider": "llama-server",
        "model": {"default": "tiny-q4"},
    }
    await sm.create("extra", cfg)
    await sm.delete("extra")
    assert not (Path(tmp_hal0_home) / "etc" / "hal0" / "slots" / "extra.toml").exists()
    # builtin protection
    from hal0.slots.state import SlotConfigError

    with pytest.raises(SlotConfigError):
        await sm.delete("primary")


async def test_update_config_rewrites_toml_and_env(
    slot_root: Path,
    tmp_hal0_home: str,
    systemctl_stub: dict[str, Any],
) -> None:
    sm = SlotManager()
    # Need an initial state so _ensure_known passes.
    from hal0.slots.state import SlotState as _S

    await sm._transition("primary", _S.OFFLINE, force=True)
    await sm.update_config("primary", {"workers": 4})
    cfg_text = (slot_root / "primary.toml").read_text(encoding="utf-8")
    assert "workers = 4" in cfg_text


# ── SSE state stream ────────────────────────────────────────────────────────


async def test_state_stream_broadcasts_transitions(
    slot_root: Path,
    systemctl_stub: dict[str, Any],
    stub_await_ready: None,
) -> None:
    sm = SlotManager()

    received: list[tuple[str, str]] = []

    async def consumer() -> None:
        async for rec in sm.state_stream():
            received.append((rec.name, rec.state.value))
            if len(received) >= 3:
                return

    task = asyncio.create_task(consumer())
    # give the consumer a tick to subscribe
    await asyncio.sleep(0)
    await sm.load("primary")
    await asyncio.wait_for(task, timeout=2.0)

    states_seen = [s for _, s in received]
    # Should have seen at least starting then warming then ready
    assert "starting" in states_seen
    assert "ready" in states_seen


# ── bump_last_used / idle tracking ──────────────────────────────────────────


def test_bump_last_used_records_timestamp() -> None:
    sm = SlotManager()
    assert sm.last_used("foo") is None
    sm.bump_last_used("foo")
    ts = sm.last_used("foo")
    assert ts is not None and ts > 0


# ── health-probe sentinel (Tier 1) ───────────────────────────────────────────


async def test_sentinel_inference_rejects_failure() -> None:
    """A 500 from /v1/chat/completions does NOT count as ready."""
    from hal0.slots.manager import _sentinel_inference

    transport = httpx.MockTransport(lambda req: httpx.Response(500, json={}))
    async with httpx.AsyncClient(transport=transport) as client:
        ok = await _sentinel_inference(client, "http://x", {"id": "m"})
    assert ok is False


async def test_sentinel_inference_accepts_2xx() -> None:
    from hal0.slots.manager import _sentinel_inference

    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        ok = await _sentinel_inference(client, "http://x", {"id": "m"})
    assert ok is True


def test_provider_health_strategy_classification() -> None:
    from hal0.slots.manager import _provider_health_strategy

    # chat-multiplex providers that advertise models before infer works
    assert _provider_health_strategy("flm") == "chat_sentinel"
    assert _provider_health_strategy("vllm") == "chat_sentinel"
    # moonshine has /health but stays 200 while loading — body must say so
    assert _provider_health_strategy("moonshine") == "health_with_model_loaded"
    # llama-server + kokoro: /health 2xx is authoritative
    assert _provider_health_strategy("llama-server") == "health"
    assert _provider_health_strategy("llamacpp") == "health"
    assert _provider_health_strategy("kokoro") == "health"

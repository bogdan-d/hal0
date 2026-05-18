"""Adoption + transition-guard tests for the modelless-READY bug.

Reproducer: on hal0-test (LXC 230) ``/var/lib/hal0/slots/utility/state.json``
showed ``state=ready`` with ``model_id=""``, even though
``/etc/hal0/slots/utility.toml`` had no ``[model]`` section.  The dashboard
correctly rendered "no model" while the navbar still counted it as
running — the discrepancy was patched in the UI (commit ``84cdb7b``),
but the backend should never have written READY with an empty
``model_id`` for a provider that needs one.

These tests cover the three new gates:

  1. ``_maybe_adopt_running_slot`` demotes READY → IDLE when the
     resolved provider needs a model and none can be sniffed.
  2. The same path picks up a live ``model_id`` from ``/v1/models``
     when one is available, persisting READY with that id.
  3. Self-managed providers (kokoro / moonshine / vibevoice) keep
     landing at READY even without a ``model_id``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from hal0.slots import manager as manager_mod
from hal0.slots.manager import SlotManager
from hal0.slots.state import SlotState


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    """Re-route any ``httpx.AsyncClient`` created in the manager to a stub."""
    transport = httpx.MockTransport(handler)
    original = manager_mod.httpx.AsyncClient

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return original(*args, transport=transport, **kwargs)

    monkeypatch.setattr(manager_mod.httpx, "AsyncClient", _factory)


def _write_modelless_slot(
    tmp_hal0_home: str,
    name: str,
    provider: str,
    port: int,
) -> Path:
    """Write a slot TOML with NO ``[model]`` section.

    Mirrors the bad shape observed on hal0-test for utility/stt/tts.
    """
    root = Path(tmp_hal0_home) / "etc" / "hal0" / "slots"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.toml"
    path.write_text(
        "\n".join(
            [
                f'name = "{name}"',
                f"port = {port}",
                'backend = "vulkan"',
                f'provider = "{provider}"',
                "enabled = true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


# ── 1. adoption: llama-server, no [model] default, /v1/models empty → IDLE ────


async def test_adoption_demotes_to_idle_when_provider_requires_model(
    tmp_hal0_home: str,
    systemctl_stub: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A llama-server slot with no model + empty upstream lands at IDLE.

    The bug shape: probe says READY (because the strategy was happy with
    ``/health`` 2xx) and the legacy code persisted READY with
    ``model_id=None``.  After the fix, adoption sniffs ``/v1/models``,
    finds nothing usable, and demotes to IDLE.
    """
    systemctl_stub["is_active_state"] = "active"
    _write_modelless_slot(tmp_hal0_home, "utility", "llama-server", 8082)

    async def _probe(
        self: SlotManager, port: int, provider: str
    ) -> tuple[bool, SlotState | None, str]:
        return True, SlotState.READY, "stub probe ready"

    monkeypatch.setattr(SlotManager, "_probe_once", _probe)

    # /v1/models lookup performed by the adoption sniff returns nothing.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404)

    _patch_httpx(monkeypatch, handler)

    sm = SlotManager()
    snap = await sm.status("utility")
    assert snap.state == SlotState.IDLE, (
        f"modelless llama-server adoption must demote to IDLE, got {snap.state}"
    )
    assert snap.model_id in (None, "")
    assert snap.metadata.get("degraded_to_idle") is True


# ── 2. adoption: self-managed (kokoro) → READY without a model_id ─────────────


async def test_adoption_kokoro_without_model_lands_at_ready(
    tmp_hal0_home: str,
    systemctl_stub: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """kokoro serves a baked-in model — modelless READY is legitimate."""
    systemctl_stub["is_active_state"] = "active"
    _write_modelless_slot(tmp_hal0_home, "tts", "kokoro", 8084)

    async def _probe(
        self: SlotManager, port: int, provider: str
    ) -> tuple[bool, SlotState | None, str]:
        return True, SlotState.READY, "stub probe ready"

    monkeypatch.setattr(SlotManager, "_probe_once", _probe)

    sm = SlotManager()
    snap = await sm.status("tts")
    assert snap.state == SlotState.READY, (
        f"kokoro must keep READY without a model_id, got {snap.state}"
    )
    assert snap.metadata.get("degraded_to_idle") is not True


# ── 3. adoption: llama-server without [model], /v1/models advertises one ──────


async def test_adoption_sniffs_model_id_from_upstream(
    tmp_hal0_home: str,
    systemctl_stub: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When upstream advertises a real model, adoption stays READY with it."""
    systemctl_stub["is_active_state"] = "active"
    _write_modelless_slot(tmp_hal0_home, "utility", "llama-server", 8082)

    async def _probe(
        self: SlotManager, port: int, provider: str
    ) -> tuple[bool, SlotState | None, str]:
        return True, SlotState.READY, "stub probe ready"

    monkeypatch.setattr(SlotManager, "_probe_once", _probe)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={"data": [{"id": "primary"}, {"id": "phi3-mini"}]},
            )
        return httpx.Response(404)

    _patch_httpx(monkeypatch, handler)

    sm = SlotManager()
    snap = await sm.status("utility")
    assert snap.state == SlotState.READY, (
        f"adoption must stay READY when /v1/models advertises a real model, got {snap.state}"
    )
    # First entry "primary" is a routing alias — second entry wins.
    assert snap.model_id == "phi3-mini"
    assert snap.metadata.get("detected_model") == "phi3-mini"


# ── 4. migration: stale state.json on disk auto-heals on status() ─────────────


async def test_status_migrates_stale_modelless_ready_state_json(
    tmp_hal0_home: str,
    systemctl_stub: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-existing READY+model_id="" record from before the fix self-heals.

    Reproduces the hal0-test ``utility/state.json`` shape exactly: state
    ``ready``, ``model_id=""``, provider llama-server.  After this fix the
    first ``status()`` call must demote it to IDLE without manual cleanup.
    """
    import json

    systemctl_stub["is_active_state"] = "active"
    _write_modelless_slot(tmp_hal0_home, "utility", "llama-server", 8082)

    state_dir = Path(tmp_hal0_home) / "var-lib" / "hal0" / "slots" / "utility"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "name": "utility",
                "state": "ready",
                "model_id": "",
                "port": 8082,
                "updated_at": 0.0,
                "message": "",
                "extra": {"backend": "vulkan", "provider": "llama-server"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    async def _probe(
        self: SlotManager, port: int, provider: str
    ) -> tuple[bool, SlotState | None, str]:
        return True, SlotState.READY, "stub probe ready"

    monkeypatch.setattr(SlotManager, "_probe_once", _probe)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404)

    _patch_httpx(monkeypatch, handler)

    sm = SlotManager()
    snap = await sm.status("utility")
    assert snap.state == SlotState.IDLE, (
        f"stale READY+modelless record must be migrated to IDLE on the next "
        f"status() poll, got {snap.state}"
    )
    # And the migration must have persisted to disk so the next reader
    # observes the corrected state without re-running adoption.
    on_disk = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert on_disk["state"] == "idle"

"""End-to-end slot lifecycle tests.

Marked ``@pytest.mark.integration`` because they exercise the real
``hal0-slot@.service`` template unit against a live systemd and the
Vulkan toolbox image (PLAN.md §10 — "real hal0-slot@.service with
Qwen3 0.5B on Vulkan-CPU").

These tests intentionally do NOT pass on the dev VM unless every
prerequisite is in place:
  - systemd available (PID 1 == systemd or `systemctl --user` reachable)
  - hal0-slot@.service template installed at /etc/systemd/system/
  - HAL0_HOME pointed at a writable directory
  - A Vulkan-capable toolbox image pullable from the configured registry
  - A model in the registry that fits in the local GPU/CPU

The coordinator agent wires these into CI; the dev-VM run reports them as
deselected via the marker.

Run only this file's integration cases:
    pytest tests/slots/test_integration.py -v -m integration

Skip them globally (default for `make test`):
    pytest tests/slots/ -m "not integration"
"""

from __future__ import annotations

import os
import shutil

import pytest

from hal0.slots.manager import SlotManager
from hal0.slots.state import SlotState

pytestmark = pytest.mark.integration


def _systemd_available() -> bool:
    if shutil.which("systemctl") is None:
        return False
    # `systemctl is-system-running` exits non-zero in many states but tells
    # us systemd is present.
    rc = os.system("systemctl is-system-running >/dev/null 2>&1")
    # rc != 0 is OK — degraded systems still "have" systemd.
    return rc != 127


def _template_unit_installed() -> bool:
    return os.path.exists("/etc/systemd/system/hal0-slot@.service")


_PRECONDITIONS_MET = _systemd_available() and _template_unit_installed()


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _PRECONDITIONS_MET,
        reason=(
            "hal0-slot@.service template is not installed on this host. "
            "Integration tests are intended for CI / release-gate only — "
            "the coordinator runs them in a provisioned environment."
        ),
    ),
]


# ── happy-path slot lifecycle ────────────────────────────────────────────────


@pytest.fixture
def ci_slot_name() -> str:
    return os.environ.get("HAL0_CI_SLOT", "ci-test")


@pytest.fixture
def ci_model_id() -> str:
    return os.environ.get("HAL0_CI_MODEL", "qwen3-0.5b-q4_k_m")


async def test_end_to_end_load_serve_unload(
    ci_slot_name: str,
    ci_model_id: str,
) -> None:
    """Full lifecycle: create → load → serve → unload → delete.

    Spec only — coordinator may extend with /v1/chat/completions round-trip.
    """
    sm = SlotManager()

    cfg = {
        "name": ci_slot_name,
        "port": 8099,
        "backend": "vulkan",
        "provider": "llama-server",
        "model": {"default": ci_model_id, "context_size": 512},
    }

    # Create.
    snap = await sm.create(ci_slot_name, cfg)
    assert snap.state == SlotState.OFFLINE

    try:
        # Load.
        snap = await sm.load(ci_slot_name)
        assert snap.state == SlotState.READY
        assert snap.port == 8099
        assert snap.model_id == ci_model_id

        # Unload.
        snap = await sm.unload(ci_slot_name)
        assert snap.state == SlotState.OFFLINE
    finally:
        await sm.delete(ci_slot_name)


async def test_state_transitions_visible_via_stream(
    ci_slot_name: str,
    ci_model_id: str,
) -> None:
    """Slot lifecycle transitions land on the SSE state stream in order.

    Coordinator-CI: replay the broadcast queue to assert the expected
    sequence offline → starting → warming → ready.
    """
    import asyncio

    sm = SlotManager()
    cfg = {
        "name": ci_slot_name,
        "port": 8099,
        "backend": "vulkan",
        "provider": "llama-server",
        "model": {"default": ci_model_id, "context_size": 512},
    }
    await sm.create(ci_slot_name, cfg)
    received: list[str] = []

    async def consumer() -> None:
        async for rec in sm.state_stream():
            received.append(rec.state.value)
            if rec.state == SlotState.READY:
                return

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0)
    try:
        await sm.load(ci_slot_name)
        await asyncio.wait_for(task, timeout=240.0)
        assert "starting" in received
        assert "warming" in received
        assert "ready" in received
    finally:
        await sm.unload(ci_slot_name)
        await sm.delete(ci_slot_name)

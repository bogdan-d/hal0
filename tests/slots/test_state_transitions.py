"""Tests for hal0.slots.state — state machine + persistence helpers.

Covers PLAN.md §5 Tier 3:
  - LEGAL_TRANSITIONS contains every documented edge
  - is_transition_legal() returns False for illegal edges
  - SlotStateRecord round-trips through write_state_atomic / read_state
  - Malformed state.json raises SlotConfigError (no silent swallow)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hal0.slots.state import (
    LEGAL_TRANSITIONS,
    IllegalSlotTransition,
    SlotConfigError,
    SlotState,
    SlotStateRecord,
    is_transition_legal,
    read_state,
    write_state_atomic,
)

# ── enum + transition map ───────────────────────────────────────────────────


def test_slot_state_enum_values() -> None:
    """Every documented state has a stable string value used on the wire."""
    expected = {
        "offline",
        "pulling",
        "starting",
        "warming",
        "ready",
        "serving",
        "idle",
        "unloading",
        "error",
    }
    actual = {s.value for s in SlotState}
    assert actual == expected, (
        f"Unexpected state set: {actual - expected} / missing {expected - actual}"
    )


def test_legal_transitions_covers_every_state() -> None:
    """LEGAL_TRANSITIONS must define an outbound edge set for every state."""
    for state in SlotState:
        assert state in LEGAL_TRANSITIONS, f"{state} is not in LEGAL_TRANSITIONS"


@pytest.mark.parametrize(
    "from_state,to_state",
    [
        (SlotState.OFFLINE, SlotState.STARTING),
        (SlotState.STARTING, SlotState.WARMING),
        (SlotState.WARMING, SlotState.READY),
        (SlotState.READY, SlotState.SERVING),
        (SlotState.SERVING, SlotState.READY),
        (SlotState.READY, SlotState.IDLE),
        (SlotState.IDLE, SlotState.UNLOADING),
        (SlotState.UNLOADING, SlotState.OFFLINE),
        (SlotState.ERROR, SlotState.OFFLINE),
    ],
)
def test_legal_transitions_happy_path(from_state: SlotState, to_state: SlotState) -> None:
    assert is_transition_legal(from_state, to_state) is True


@pytest.mark.parametrize(
    "from_state,to_state",
    [
        # cannot jump straight from offline to ready
        (SlotState.OFFLINE, SlotState.READY),
        # cannot transition from offline to serving
        (SlotState.OFFLINE, SlotState.SERVING),
        # cannot back into pulling from ready
        (SlotState.READY, SlotState.PULLING),
        # cannot transition from unloading back into ready
        (SlotState.UNLOADING, SlotState.READY),
        # cannot transition from serving into unloading directly
        (SlotState.SERVING, SlotState.UNLOADING),
    ],
)
def test_illegal_transitions(from_state: SlotState, to_state: SlotState) -> None:
    assert is_transition_legal(from_state, to_state) is False


def test_illegal_transition_error_is_hal0_error() -> None:
    """IllegalSlotTransition has the correct error envelope code."""
    exc = IllegalSlotTransition("test", details={"slot": "x"})
    assert exc.code == "slot.illegal_transition"
    assert exc.status == 409
    assert exc.details == {"slot": "x"}


# ── persistence ──────────────────────────────────────────────────────────────


def test_state_record_round_trip(tmp_path: Path) -> None:
    """write_state_atomic → read_state preserves all fields."""
    record = SlotStateRecord(
        name="primary",
        state=SlotState.READY,
        model_id="qwen3-4b-q4_k_m",
        port=8081,
        message="boot complete",
        extra={"backend": "vulkan"},
    )
    path = tmp_path / "state.json"
    write_state_atomic(path, record)
    loaded = read_state(path)
    assert loaded is not None
    assert loaded.name == "primary"
    assert loaded.state == SlotState.READY
    assert loaded.model_id == "qwen3-4b-q4_k_m"
    assert loaded.port == 8081
    assert loaded.message == "boot complete"
    assert loaded.extra == {"backend": "vulkan"}


def test_read_state_missing_returns_none(tmp_path: Path) -> None:
    assert read_state(tmp_path / "absent.json") is None


def test_read_state_malformed_raises(tmp_path: Path) -> None:
    """A malformed state.json surfaces SlotConfigError, not a silent None."""
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SlotConfigError):
        read_state(path)


def test_read_state_unknown_value_raises(tmp_path: Path) -> None:
    """A state.json with a bogus state string raises SlotConfigError."""
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"name": "x", "state": "spinning"}), encoding="utf-8")
    with pytest.raises(SlotConfigError):
        read_state(path)


def test_write_state_atomic_is_atomic(tmp_path: Path) -> None:
    """A successful write leaves no .hal0-state-*.tmp orphans in the dir."""
    path = tmp_path / "state.json"
    record = SlotStateRecord(name="x", state=SlotState.OFFLINE)
    write_state_atomic(path, record)
    leftovers = list(tmp_path.glob(".hal0-state-*.tmp"))
    assert leftovers == [], f"tmp files leaked: {leftovers}"
    # File is JSON, deterministic.
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["state"] == "offline"
    assert parsed["name"] == "x"

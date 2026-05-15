"""Slot lifecycle state machine.

Defines the canonical SlotState enum used by SlotManager, the dashboard SSE
stream, and the state.json persistence layer.

State machine (PLAN.md §5 Tier 3):

    offline → pulling → starting → warming → ready
                                             ↓
                                           serving ↔ idle → unloading → offline
                                             ↓
                                           error

Transitions are atomic, persisted to /var/lib/hal0/slots/<name>/state.json,
and streamable via SSE.  The dashboard surfaces real transitions, not
systemd snapshots.

See PLAN.md §5 Tier 3 and ARCHITECTURE.md §State.
"""

from __future__ import annotations

from enum import StrEnum


class SlotState(StrEnum):
    """Lifecycle states for a hal0 inference slot.

    Each value is also its JSON/SSE wire representation.
    """

    OFFLINE = "offline"
    """Slot is not running.  No systemd unit active."""

    PULLING = "pulling"
    """Model files are being downloaded or verified.  systemd unit not yet started."""

    STARTING = "starting"
    """systemd unit has been started; waiting for the container to come up."""

    WARMING = "warming"
    """Container is up; health probe is returning non-ready responses while the
    model loads into VRAM / GTT."""

    READY = "ready"
    """Slot passed the full health probe (non-empty /v1/models + sentinel
    completion). Ready to serve requests."""

    SERVING = "serving"
    """An inference request is actively in-flight on this slot."""

    IDLE = "idle"
    """Slot is ready but has received no request for longer than the idle
    timeout. Candidate for unloading."""

    UNLOADING = "unloading"
    """Graceful shutdown in progress.  systemd stop issued; waiting for the
    container to exit."""

    ERROR = "error"
    """Slot has failed.  Details in state.json and journald."""


#: Legal transitions: {from_state -> set of reachable states}
#: Enforcement is the SlotManager's responsibility; this is a reference map.
LEGAL_TRANSITIONS: dict[SlotState, frozenset[SlotState]] = {
    SlotState.OFFLINE: frozenset({SlotState.PULLING, SlotState.STARTING}),
    SlotState.PULLING: frozenset({SlotState.STARTING, SlotState.ERROR, SlotState.OFFLINE}),
    SlotState.STARTING: frozenset({SlotState.WARMING, SlotState.ERROR, SlotState.OFFLINE}),
    SlotState.WARMING: frozenset({SlotState.READY, SlotState.ERROR, SlotState.OFFLINE}),
    SlotState.READY: frozenset(
        {SlotState.SERVING, SlotState.IDLE, SlotState.UNLOADING, SlotState.ERROR}
    ),
    SlotState.SERVING: frozenset({SlotState.READY, SlotState.IDLE, SlotState.ERROR}),
    SlotState.IDLE: frozenset({SlotState.SERVING, SlotState.UNLOADING, SlotState.READY}),
    SlotState.UNLOADING: frozenset({SlotState.OFFLINE, SlotState.ERROR}),
    SlotState.ERROR: frozenset({SlotState.OFFLINE, SlotState.PULLING, SlotState.STARTING}),
}


def is_transition_legal(from_state: SlotState, to_state: SlotState) -> bool:
    """Return True if the transition from_state → to_state is allowed."""
    return to_state in LEGAL_TRANSITIONS.get(from_state, frozenset())

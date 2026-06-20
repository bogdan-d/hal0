"""Shared recording fakes for the Stacks convergence tests.

Mirrors the FakeSlotManager pattern used in tests/capabilities: async methods
that record their calls without touching systemd/containers, so converge()'s
decision logic can be asserted by inspecting the call list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hal0.slots.state import SlotState


@dataclass
class FakeSnap:
    """A minimal Slot snapshot: just the fields converge() reads."""

    name: str
    state: SlotState
    model_id: str | None = None


class RecordingSlotManager:
    """Records load/swap/unload/list calls; serves a configurable pre-state."""

    def __init__(self, snapshots: list[FakeSnap] | None = None) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        self._snapshots = list(snapshots or [])

    async def list(self) -> list[FakeSnap]:
        self.calls.append(("list", "", None))
        return list(self._snapshots)

    async def load(self, slot_name: str, model_id: str | None = None) -> FakeSnap:
        self.calls.append(("load", slot_name, model_id))
        return FakeSnap(slot_name, SlotState.READY, model_id)

    async def swap(self, slot_name: str, new_model_id: str) -> FakeSnap:
        self.calls.append(("swap", slot_name, new_model_id))
        return FakeSnap(slot_name, SlotState.READY, new_model_id)

    async def unload(self, slot_name: str) -> FakeSnap:
        self.calls.append(("unload", slot_name, None))
        return FakeSnap(slot_name, SlotState.OFFLINE, None)


class RecordingOrchestrator:
    """Records capability apply() calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def apply(self, slot: str, child: str, partial: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((slot, child, dict(partial)))
        return {"slot": slot, "child": child, "status": "ready"}

"""Capability slots — operator-facing overlay over the slot manager.

Bridges the dashboard's "capability-grouped slots" concept (embed/voice/img,
each with multiple children) to the existing single-model-per-slot
``SlotManager`` infrastructure. The overlay does NOT rewrite the slot
schema — it persists the user's selections in ``capabilities.toml`` and
dispatches lifecycle calls to the underlying slots.

See ``capabilities/orchestrator.py`` for the bridge and
``api/routes/capabilities.py`` for the HTTP surface.
"""

from __future__ import annotations

from hal0.capabilities.config import CapabilityConfig, CapabilitySelection
from hal0.capabilities.orchestrator import CapabilityOrchestrator

__all__ = [
    "CapabilityConfig",
    "CapabilityOrchestrator",
    "CapabilitySelection",
]

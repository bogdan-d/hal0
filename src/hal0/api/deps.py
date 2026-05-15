"""FastAPI dependency injection helpers.

Slot manager, registry, dispatcher, hardware probe etc. wire in here so
route handlers receive concrete instances via `Depends()`. Stubs for now;
implementations land in Phase 1.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends


def get_slot_manager() -> object:  # TODO Phase 1: return SlotManager
    raise NotImplementedError("slot manager not wired yet (Phase 1)")


def get_registry() -> object:  # TODO Phase 1: return ModelRegistry
    raise NotImplementedError("registry not wired yet (Phase 1)")


def get_dispatcher() -> object:  # TODO Phase 1: return Dispatcher
    raise NotImplementedError("dispatcher not wired yet (Phase 1)")


def get_hardware() -> object:  # TODO Phase 1: return HardwareProbe
    raise NotImplementedError("hardware probe not wired yet (Phase 1)")


SlotManagerDep = Annotated[object, Depends(get_slot_manager)]
RegistryDep = Annotated[object, Depends(get_registry)]
DispatcherDep = Annotated[object, Depends(get_dispatcher)]
HardwareDep = Annotated[object, Depends(get_hardware)]

"""FastAPI dependency injection helpers.

The actual instances are created in the app lifespan (see
:mod:`hal0.api`) and stashed on ``app.state``; these dependency
functions read them back out so route handlers receive concrete objects
via :func:`fastapi.Depends`.

Cross-request singletons (dispatcher, upstream registry, model registry,
slot manager, hardware probe) all live on ``app.state``; the helpers
return ``None``-safe stubs if the app didn't populate one (so unit tests
that don't need the dependency can omit the lifespan).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast

from fastapi import Depends, Request

if TYPE_CHECKING:
    from hal0.dispatcher.router import Dispatcher
    from hal0.hardware.probe import HardwareProbe
    from hal0.registry.store import ModelRegistry
    from hal0.slots.manager import SlotManager


def _state(request: Request, attr: str) -> object | None:
    return getattr(request.app.state, attr, None)


def get_slot_manager(request: Request) -> SlotManager:
    obj = _state(request, "slot_manager")
    if obj is None:
        raise RuntimeError("slot manager not initialized (lifespan did not run)")
    return cast("SlotManager", obj)


def get_registry(request: Request) -> ModelRegistry:
    obj = _state(request, "model_registry")
    if obj is None:
        raise RuntimeError("model registry not initialized (lifespan did not run)")
    return cast("ModelRegistry", obj)


def get_dispatcher(request: Request) -> Dispatcher:
    obj = _state(request, "dispatcher")
    if obj is None:
        raise RuntimeError("dispatcher not initialized (lifespan did not run)")
    return cast("Dispatcher", obj)


def get_hardware(request: Request) -> HardwareProbe:
    obj = _state(request, "hardware_probe")
    if obj is None:
        raise RuntimeError("hardware probe not initialized (lifespan did not run)")
    return cast("HardwareProbe", obj)


SlotManagerDep = Annotated["SlotManager", Depends(get_slot_manager)]
RegistryDep = Annotated["ModelRegistry", Depends(get_registry)]
DispatcherDep = Annotated["Dispatcher", Depends(get_dispatcher)]
HardwareDep = Annotated["HardwareProbe", Depends(get_hardware)]

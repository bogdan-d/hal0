"""hal0.registry — Atomic TOML-backed model catalog.

The registry is the single source of truth for "what models exist on this
host."  It persists model metadata as atomic TOML files under
/var/lib/hal0/registry/ and uses mtime polling to invalidate its in-memory
cache when files change on disk.

Slot configs reference model IDs from the registry.  If a model is deleted,
any slot referencing it fails to load with a structured error
({"error": {"code": "model.not_found", ...}}).

Port target: haloai lib/registry.py (split into store + model).
See PLAN.md §3 and ARCHITECTURE.md §Key boundaries.

Key exports:
    ModelRegistry — primary entry point for all registry operations.
    Model         — pydantic model for a single registry entry.
"""

from __future__ import annotations

from hal0.registry.model import Model
from hal0.registry.store import ModelAlreadyExists, ModelNotFound, ModelRegistry, RegistryError

__all__ = [
    "Model",
    "ModelAlreadyExists",
    "ModelNotFound",
    "ModelRegistry",
    "RegistryError",
]

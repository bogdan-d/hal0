"""ModelRegistry — atomic TOML-backed model catalog.

The registry is the single source of truth for "what models exist."
It persists model metadata as atomic TOML files under
/var/lib/hal0/registry/ and uses mtime polling to invalidate its
in-memory cache when files change on disk.

Port target: haloai lib/registry.py.
See PLAN.md §3 and ARCHITECTURE.md §Key boundaries ("registry is the only
source of truth for what models exist").
"""

from __future__ import annotations

from typing import Any

from hal0.registry.model import Model


class RegistryError(ValueError):
    """Base error for registry operations."""


class ModelNotFound(RegistryError, KeyError):
    """The requested model id is not in the registry."""


class ModelAlreadyExists(RegistryError):
    """add() called but the model id is already present."""


class ModelRegistry:
    """Atomic TOML-backed model registry.

    Thread-safety: a module-level RLock guards all reads and writes.
    FastAPI sync routes run on the threadpool; the Dispatcher runs on the
    event loop.  Both paths share this registry, so the lock must be
    threading-aware.

    The mtime cache invalidates itself when registry files change on disk,
    allowing direct file edits to take effect on the next access.
    """

    def __init__(self, registry_dir: str | None = None) -> None:
        """Initialise the registry.

        Args:
            registry_dir: Override the registry directory.  If None, reads
                          from hal0.config.paths.var_lib() / "registry".
        """
        self._registry_dir = registry_dir  # resolved in Phase 1

    def list(self) -> list[Model]:
        """Return all registered models.

        Raises:
            NotImplementedError: Until Phase 1 port from haloai lib/registry.py.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/registry.py")

    def get(self, model_id: str) -> Model:
        """Return a single model by id.

        Raises:
            ModelNotFound: If the model is not in the registry.
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/registry.py")

    def add(self, model: Model) -> None:
        """Add a new model to the registry.

        Writes atomically using tempfile + os.replace.

        Raises:
            ModelAlreadyExists: If the model id is already present.
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/registry.py")

    def remove(self, model_id: str) -> bool:
        """Remove a model from the registry.

        Returns True if the model was present and removed, False if absent.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/registry.py")

    def update(self, model_id: str, updates: dict[str, Any]) -> Model:
        """Partially update a model entry.

        Raises:
            ModelNotFound: If the model is not in the registry.
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/registry.py")

    def route_for(self, model_id: str) -> str | None:
        """Return the upstream URL for a model, or None if not assigned.

        Used by the Dispatcher to resolve registry bindings.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/registry.py")

    def reload(self) -> None:
        """Force-invalidate the mtime cache; next access re-reads from disk.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/registry.py")

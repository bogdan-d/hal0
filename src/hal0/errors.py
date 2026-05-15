"""Leaf-module home for the structured-error base class.

Lives here (not in ``hal0.api.middleware.error_codes``) so non-api modules
— probes, loaders, providers — can raise typed errors without triggering
the api import chain. The middleware re-exports ``Hal0Error`` for the
import path everything else has always used.
"""

from __future__ import annotations

from typing import Any


class Hal0Error(Exception):
    """Base class for typed errors with stable codes.

    Subclasses set ``code`` (dotted namespace, e.g. ``slot.not_ready``) and
    optionally ``status`` (HTTP status code surfaced by the api middleware).
    """

    code: str = "system.internal"
    status: int = 500

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


__all__ = ["Hal0Error"]

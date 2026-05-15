"""Moonshine STT voice provider — hal0.voice re-export and stub.

This module will contain hal0-specific voice provider glue once the
Moonshine server code is ported from haloai lib/voice/moonshine_server.py.

The inference provider (MoonshineProvider) lives in hal0.providers.moonshine.
This module is for voice-pipeline-specific helpers that don't belong in
the generic provider abstraction (e.g. WebSocket protocol helpers, streaming
transcript event models).

Port target: haloai lib/voice/moonshine_server.py.
See PLAN.md §1 (voice providers) and §3 (new modules — hal0/voice/).
"""

from __future__ import annotations

# Re-export the provider for convenience — callers can import from either location.
from hal0.providers.moonshine import MoonshineProvider

__all__ = ["MoonshineProvider"]


# NOTE: revisit in Phase 1 — add WebSocket transcript event models and
# streaming helpers once moonshine_server.py is ported.

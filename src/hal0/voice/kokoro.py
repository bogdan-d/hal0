"""Kokoro TTS voice provider — hal0.voice re-export and stub.

This module will contain hal0-specific voice provider glue once the
Kokoro server is ported and any voice-pipeline-specific helpers are
identified.

The inference provider (KokoroProvider) lives in hal0.providers.kokoro.
This module is for voice-pipeline-specific helpers (e.g. SSML processing,
voice selection helpers) that don't belong in the generic provider ABC.

Port target: new module (haloai has Kokoro as a slot config, not a typed class).
See PLAN.md §1 (voice providers) and §3 (new modules — hal0/voice/).
"""

from __future__ import annotations

# Re-export the provider for convenience.
from hal0.providers.kokoro import KokoroProvider

__all__ = ["KokoroProvider"]


# NOTE: revisit in Phase 1 — add voice selection helpers and SSML processing
# stubs once the Kokoro server implementation is in place.

"""hal0.voice — Moonshine STT + Kokoro TTS provider glue.

Re-exports the voice-related providers from hal0.providers for callers
that want a single import location for voice functionality.

This module is NOT the Hermes voice gateway (which is stripped entirely
per PLAN.md §1 Strip).  It is only the inference provider wrappers for
Moonshine (STT) and Kokoro (TTS).

Port target: haloai lib/voice/ (the inference pieces, not the voice gateway).
See PLAN.md §1 ("provider slots are kept") and §3 (new modules).

Key exports:
    MoonshineProvider  — STT backend (re-exported from hal0.providers.moonshine)
    KokoroProvider     — TTS backend (re-exported from hal0.providers.kokoro)
"""

from __future__ import annotations

from hal0.providers.kokoro import KokoroProvider
from hal0.providers.moonshine import MoonshineProvider

__all__ = [
    "KokoroProvider",
    "MoonshineProvider",
]

"""hal0.updater — Atomic self-update with cosign-verified releases.

Implements `hal0 update [--channel=stable|nightly] [--check] [--rollback]`.

The updater fetches hal0.dev/releases/latest.json, verifies the cosign
signature, extracts to a versioned directory, runs any pending config
migrations, and atomically swaps the /usr/lib/hal0/current symlink.
Running slots are NOT restarted unless --restart-slots is passed.

Rollback swaps the symlink back to the retained previous version and
restarts hal0-api.

Port target: haloai lib/updater.py (569 lines).
Depends on: cosign CLI on PATH, signed release pipeline (Phase 5).
See PLAN.md §9 and §15 Phase 5.

Key exports:
    Updater — check / pull / rollback methods.
"""

from __future__ import annotations

from hal0.updater.updater import Updater

__all__ = [
    "Updater",
]

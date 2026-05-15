"""v1 — initial published schema.

# TIER3: this is the identity migration.  v1 is the first published
# config schema; there is no v0, so the v1 transform takes a v0-shaped
# (i.e. unversioned, legacy) dict and stamps it as v1 with no other
# changes.  Future migrations (v2, v3, ...) implement real transforms.

The migration is registered via the decorator below; importing this
module side-effects MIGRATIONS[1] = migrate_v0_to_v1.

See PLAN.md §5 Tier 3 ("Config evolution / migration tooling").
"""

from __future__ import annotations

from typing import Any

from hal0.config.migrations import register


@register(1)
def migrate_v0_to_v1(data: dict[str, Any]) -> dict[str, Any]:
    """Identity migration — v0 (unversioned) → v1.

    No structural changes.  The runner stamps ``meta.schema_version = 1``
    after this returns, so the only contract here is "don't lose data."

    Args:
        data: The raw ``hal0.toml`` dict at v0 / unversioned.

    Returns:
        A new dict equivalent to ``data``.  Caller deep-copied already;
        we return it unchanged.
    """
    # NOTE: the runner already deep-copied `data` before invoking us, so
    # mutating in place would be fine.  Returning as-is is cleaner.
    return data

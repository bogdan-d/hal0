"""Cognee → Hindsight migration (brain-redesign P2, [Q10]).

The platform Cognee store has been dark since v0.4 (memory OFF), so this is
likely a no-op. The dry-run reads the sidecar SQLite (the canonical filter
source) and reports rows mapped/unmapped without touching Hindsight. Cognee
data stays read-only.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from hal0.memory.hindsight_provider import namespace_to_bank


def migrate_cognee_to_hindsight_dryrun(*, cognee_dir: str | Path) -> dict[str, Any]:
    sidecar = Path(cognee_dir) / "hal0_memory_index.sqlite"
    if not sidecar.exists():
        return {"rows_total": 0, "rows_mapped": 0, "rows_unmapped": 0, "noop": True}
    with sqlite3.connect(sidecar) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, dataset FROM hal0_memory_items").fetchall()
    total = len(rows)
    if total == 0:
        return {"rows_total": 0, "rows_mapped": 0, "rows_unmapped": 0, "noop": True}
    mapped = 0
    for row in rows:
        bank = namespace_to_bank(row["dataset"])
        if bank:
            mapped += 1
    return {
        "rows_total": total,
        "rows_mapped": mapped,
        "rows_unmapped": total - mapped,
        "noop": False,
    }

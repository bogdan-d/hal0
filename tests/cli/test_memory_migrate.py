"""hal0 memory migrate --dry-run (P2). No-op on empty/stale Cognee store."""

from __future__ import annotations

import sqlite3

from hal0.memory.migrate import migrate_cognee_to_hindsight_dryrun


def test_dry_run_reports_zero_on_empty_store(tmp_path):
    # No sidecar file → empty store → no-op.
    report = migrate_cognee_to_hindsight_dryrun(cognee_dir=tmp_path)
    assert report == {"rows_total": 0, "rows_mapped": 0, "rows_unmapped": 0, "noop": True}


def test_dry_run_tolerates_null_dataset_rows(tmp_path):
    # A sidecar row with NULL dataset must not crash the dry-run; it counts
    # as unmapped rather than raising AttributeError.
    sidecar = tmp_path / "hal0_memory_index.sqlite"
    conn = sqlite3.connect(sidecar)
    conn.execute("CREATE TABLE hal0_memory_items (id TEXT, dataset TEXT)")
    conn.execute("INSERT INTO hal0_memory_items VALUES ('a', 'shared')")
    conn.execute("INSERT INTO hal0_memory_items VALUES ('b', NULL)")
    conn.commit()
    conn.close()
    report = migrate_cognee_to_hindsight_dryrun(cognee_dir=tmp_path)
    assert report == {"rows_total": 2, "rows_mapped": 1, "rows_unmapped": 1, "noop": False}

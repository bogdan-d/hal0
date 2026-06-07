"""hal0 memory migrate --dry-run (P2). No-op on empty/stale Cognee store."""

from __future__ import annotations

from hal0.memory.migrate import migrate_cognee_to_hindsight_dryrun


def test_dry_run_reports_zero_on_empty_store(tmp_path):
    # No sidecar file → empty store → no-op.
    report = migrate_cognee_to_hindsight_dryrun(cognee_dir=tmp_path)
    assert report == {"rows_total": 0, "rows_mapped": 0, "rows_unmapped": 0, "noop": True}

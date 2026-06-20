"""Unit tests for hal0.install.perms — the declarative ownership table.

Covers:
  * ``plan()`` reports no drift when disk matches the table (the Phase-0 no-op).
  * Drift is detected per owner / group / mode; absent paths are ``absent``,
    never ``changed``.
  * Glob rows expand to one diff per matching child.
  * ``commit()`` applies drifted diffs and rolls back atomically on failure.
  * ``audit_rows`` renders the ok / drift / absent vocabulary.
  * ``ownership_table()`` builds under HAL0_HOME so it is test-isolated.

The plan/diff/commit logic is exercised through injected ``observe_fn`` /
``chown`` / ``chmod`` seams so no real privileged filesystem is needed.
"""

from __future__ import annotations

import grp
import os
import pwd
from pathlib import Path

import pytest

from hal0.config import paths
from hal0.install import perms


def _me() -> tuple[str, str]:
    return (
        pwd.getpwuid(os.getuid()).pw_name,
        grp.getgrgid(os.getgid()).gr_name,
    )


def _obs(path: Path, owner: str, group: str, mode: int) -> perms.PermObservation:
    return perms.PermObservation(path=path, exists=True, owner=owner, group=group, mode=mode)


# ── plan / drift ──────────────────────────────────────────────────────────────


def test_plan_is_noop_when_disk_matches_table() -> None:
    row = perms.PermRow(Path("/etc/hal0/hal0.toml"), "root", "root", 0o600, role="hal0.toml")
    observe = lambda p: _obs(p, "root", "root", 0o600)  # noqa: E731
    pl = perms.plan([row], observe_fn=observe)
    assert pl.changed is False
    assert pl.drifted == ()
    assert pl.diffs[0].changed is False


@pytest.mark.parametrize(
    "obs_owner,obs_group,obs_mode",
    [
        ("hal0", "root", 0o600),  # wrong owner
        ("root", "hal0", 0o600),  # wrong group
        ("root", "root", 0o644),  # wrong mode
    ],
)
def test_plan_detects_each_drift_axis(obs_owner: str, obs_group: str, obs_mode: int) -> None:
    row = perms.PermRow(Path("/etc/hal0/hal0.toml"), "root", "root", 0o600)
    pl = perms.plan([row], observe_fn=lambda p: _obs(p, obs_owner, obs_group, obs_mode))
    assert pl.changed is True
    assert len(pl.drifted) == 1


def test_absent_path_is_not_changed() -> None:
    row = perms.PermRow(Path("/var/lib/hal0/secrets"), "root", "root", 0o755)
    absent = lambda p: perms.PermObservation(p, exists=False, owner=None, group=None, mode=None)  # noqa: E731
    pl = perms.plan([row], observe_fn=absent)
    assert pl.changed is False
    assert pl.diffs[0].changed is False
    rows = perms.audit_rows(pl)
    assert rows[0]["status"] == "absent"


# ── glob expansion against a real tmp tree ────────────────────────────────────


def test_glob_row_expands_and_noops_on_self_owned_tree(tmp_path: Path) -> None:
    slots = tmp_path / "slots"
    slots.mkdir()
    (slots / "agent.toml").write_text("x = 1\n")
    (slots / "util.toml").write_text("y = 2\n")
    owner, group = _me()
    # Declare the table to match what this test process actually owns -> no-op.
    dir_mode = perms.observe(slots).mode
    file_mode = perms.observe(slots / "agent.toml").mode
    assert dir_mode is not None and file_mode is not None
    row = perms.PermRow(
        slots, owner, group, dir_mode, glob="*.toml", child_mode=file_mode, role="slots"
    )
    pl = perms.plan([row])  # real observe
    # dir + 2 files = 3 diffs, all clean (dir keeps dir_mode, files get child_mode)
    assert len(pl.diffs) == 3
    assert pl.changed is False

    # A row whose declared file mode differs from disk -> that file drifts.
    pl2 = perms.plan(
        [perms.PermRow(slots / "agent.toml", owner, group, file_mode ^ 0o044, role="agent")]
    )
    assert pl2.changed is True


# ── commit / rollback ─────────────────────────────────────────────────────────


def _diff(path: Path, before: perms.PermObservation, owner: str, group: str, mode: int):
    return perms.PermDiff(path=path, before=before, owner=owner, group=group, mode=mode, role="r")


def test_commit_applies_only_drifted_and_records_calls() -> None:
    owner, group = _me()
    chown_calls: list[tuple[str, int, int]] = []
    chmod_calls: list[tuple[str, int]] = []
    # one clean (skipped), one drifted (applied)
    clean = _diff(Path("/a"), _obs(Path("/a"), owner, group, 0o600), owner, group, 0o600)
    dirty = _diff(Path("/b"), _obs(Path("/b"), owner, group, 0o644), owner, group, 0o600)
    pl = perms.OwnershipPlan(diffs=(clean, dirty))
    changed = perms.commit(
        pl,
        chown=lambda p, u, g: chown_calls.append((p, u, g)),
        chmod=lambda p, m: chmod_calls.append((p, m)),
    )
    assert changed == [Path("/b")]
    assert chmod_calls == [("/b", 0o600)]
    assert len(chown_calls) == 1


def test_commit_rolls_back_on_failure() -> None:
    owner, group = _me()
    applied_chmod: list[tuple[str, int]] = []

    def chmod(p: str, m: int) -> None:
        if p == "/second":
            raise PermissionError("boom")
        applied_chmod.append((p, m))

    first = _diff(Path("/first"), _obs(Path("/first"), owner, group, 0o644), owner, group, 0o600)
    second = _diff(Path("/second"), _obs(Path("/second"), owner, group, 0o644), owner, group, 0o600)
    pl = perms.OwnershipPlan(diffs=(first, second))
    with pytest.raises(PermissionError):
        perms.commit(pl, chown=lambda p, u, g: None, chmod=chmod)
    # /first applied (0o600), then /second failed -> /first rolled back to 0o644
    assert applied_chmod == [("/first", 0o600), ("/first", 0o644)]


# ── audit + table smoke ───────────────────────────────────────────────────────


def test_audit_rows_status_vocabulary() -> None:
    owner, group = _me()
    clean = _diff(Path("/a"), _obs(Path("/a"), owner, group, 0o600), owner, group, 0o600)
    dirty = _diff(Path("/b"), _obs(Path("/b"), "root", "root", 0o644), owner, group, 0o600)
    absent = _diff(
        Path("/c"),
        perms.PermObservation(Path("/c"), exists=False, owner=None, group=None, mode=None),
        owner,
        group,
        0o600,
    )
    rows = perms.audit_rows(perms.OwnershipPlan(diffs=(clean, dirty, absent)))
    assert [r["status"] for r in rows] == ["ok", "drift", "absent"]


def test_ownership_table_builds_under_hal0_home(tmp_hal0_home: str) -> None:
    table = perms.ownership_table()
    assert table, "table must not be empty"
    assert all(isinstance(r, perms.PermRow) for r in table)
    home = Path(tmp_hal0_home)
    # every declared path lives under the isolated HAL0_HOME tree
    for row in table:
        assert home in row.target.parents or row.target == home, row.target
    # the config root + slots dir are non-optional anchors
    targets = {r.target for r in table}
    assert paths.etc() in targets
    assert paths.slots_config_dir() in targets

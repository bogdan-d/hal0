"""OwnershipStore — one declarative truth for filesystem ownership + mode.

hal0's path ownership is currently set by ~15 scattered ``chown``/``chmod``/
``install -o`` calls in ``installer/install.sh`` plus ad-hoc fixups, with no
single place that says "this path should be owned by X:Y mode Z". That spread is
the filesystem-layer twin of the slot-config "too many cooks" problem #697
solved for ``slots/*.toml``: the cure is the same shape — one declarative table,
a compute-only ``plan()`` that snapshots disk, an atomic ``commit()`` with
rollback, and a ``drift`` audit that reports (never silently repairs).

This module mirrors :mod:`hal0.slot_config` and :mod:`hal0.stacks.apply`
deliberately: :class:`PermObservation` is the ownership analogue of
``FileState`` (it snapshots ``owner``/``group``/``mode`` rather than TOML
content), :class:`OwnershipPlan` is the analogue of ``ChangeSet``, and
:meth:`OwnershipStore.commit` rolls back exactly like ``SlotConfigStore.commit``.

With ``service_user="root"`` (the default) :func:`ownership_table` encodes the
*current* root-era values, so ``plan()`` on a freshly-installed box reports
nothing changed and ``commit()`` writes nothing — the machinery + single table +
``doctor perms`` audit are a pure no-op for existing installs.

THE HARDENED FLIP (``service_user != "root"``, gated behind the ``HAL0_USER``
installer env) is a data-only change in :func:`ownership_table`: ``/etc/hal0``
and its mutable contents become ``service_user``-owned (the config root setgid
``2775`` so the daemon's temp-file+rename rewrites work), while ``agents/`` and
``secrets/`` stay ``root:root``; ``hal0-api`` drops to ``User=hal0`` via an
installer drop-in. The privileged seam from #943 is the prerequisite. The
plan/commit/audit machinery here does not change.

Design notes:
  - ``owner``/``group`` are resolved to uid/gid at *commit* time via
    :mod:`pwd`/:mod:`grp`, so the table is portable across boxes where the
    ``hal0`` uid differs.
  - A row may be ``optional`` (skipped when absent — e.g. ``secrets/`` only
    exists once an agent is provisioned) or a ``glob`` (``slots/*.toml``).
  - Stat/chown/chmod are injected seams so the plan/diff/audit logic is unit
    tested without a real privileged filesystem.
"""

from __future__ import annotations

import contextlib
import grp
import logging
import os
import pwd
import stat as stat_mod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from hal0.config import paths

log = logging.getLogger(__name__)


# ── the declarative table ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class PermRow:
    """One path's declared ownership + mode.

    ``mode`` is the permission bits only (e.g. ``0o755`` or ``0o2775`` with the
    setgid bit) — the file-type bits returned by ``os.stat`` are masked off
    before comparison so a dir's mode compares cleanly.
    """

    target: Path
    owner: str
    group: str
    mode: int  # the dir's / file's own mode
    glob: str | None = None  # when set, ``target`` is a dir and this globs its children
    child_mode: int | None = None  # mode for globbed children (dirs and files differ)
    optional: bool = True  # skip silently when the path is absent
    role: str = ""  # human label for the audit table

    @property
    def label(self) -> str:
        return self.role or str(self.target)


def ownership_table(
    *,
    service_user: str = "root",
    service_group: str = "hal0",
) -> list[PermRow]:
    """THE single source of truth for hal0 path ownership.

    ``service_user="root"`` (the default) reproduces the current on-disk
    root-era layout, so applying it is a no-op — existing installs are
    untouched. ``service_group`` is the shared ``hal0`` group that already
    owns ``/opt/hal0`` (setgid) and ``/var/lib/hal0``.

    THE HARDENED FLIP (``service_user != "root"``, gated behind ``HAL0_USER``):
    when the API runs as an unprivileged service user, ``/etc/hal0`` and its
    *mutable* contents become ``service_user``-owned so the daemon can atomically
    rewrite them (temp-file + ``rename``, which needs *directory* write — not
    just file write). The config root itself is ``2775`` (setgid) so files the
    service or the ``hal0`` group create there inherit the shared group.

    NOTE: the hardened "unprivileged service_user" install mode and its
    ``hal0-slotctl`` privilege seam were removed — hal0-api runs as root. This
    table is now exercised only with ``service_user="root"`` (by ``hal0 doctor``);
    the non-root branches are retained for reference but no longer wired in.

    Two subtrees stay ``root:root`` even under the flip:
      * ``agents/`` — the dashboard-only Hermes allow-list world (#843); the API
        only reads it.
      * ``secrets/`` — systemd reads ``EnvironmentFile`` here *as root* before
        dropping to the service user, so it must not be service-writable.

    The root-era values below are the *current* observed values, intentionally —
    including the warts (``api.env`` 0644, ``hal0.toml`` 0600). Those are not
    changed by the flip either; the flip changes *ownership*, not the file modes.
    See module docstring.
    """
    etc = paths.etc()
    var_lib = paths.var_lib()
    var_log = paths.var_log()

    # Whether to apply the hardened flip. When False, every row below is
    # byte-identical to the root-era table (existing installs unchanged).
    flipped = service_user != "root"
    # Owner/group for the service-writable config surface. Under the flip the
    # config root is setgid (2775) so the shared hal0 group keeps write across
    # both daemon- and group-created files; root-era keeps the plain 0755 dir.
    etc_owner = service_user if flipped else "root"
    etc_group = service_group if flipped else "root"
    etc_dir_mode = 0o2775 if flipped else 0o755
    slots_dir_mode = 0o2775 if flipped else 0o755
    # Slot/state runtime owner — already service-owned today (defaulting the
    # root-era "root" service_user to the literal hal0 service account).
    state_owner = service_user if flipped else "hal0"

    return [
        # ── /etc/hal0 — config seed (root-owned today; service-owned under flip) ─
        # The API atomically rewrites slots/*.toml, capabilities.toml, hal0.toml,
        # api.env and chat-templates via temp-file + rename, which needs *dir*
        # write on /etc/hal0 — hence the dir (and its mutable files) flip to the
        # service user. agents/ + secrets/ below stay root:root.
        PermRow(
            etc, etc_owner, etc_group, etc_dir_mode, optional=False, role="/etc/hal0 (config root)"
        ),
        PermRow(paths.hal0_toml(), etc_owner, etc_group, 0o600, role="hal0.toml"),
        PermRow(etc / "profiles.toml", etc_owner, etc_group, 0o600, role="profiles.toml"),
        # FIXME(phase4): api.env is 0644 (world-readable) but may carry tokens —
        # candidate for 0640 root:hal0 under the hardened model.
        PermRow(etc / "api.env", etc_owner, etc_group, 0o644, role="api.env"),
        PermRow(etc / "capabilities.toml", etc_owner, etc_group, 0o600, role="capabilities.toml"),
        PermRow(etc / "upstreams.toml", etc_owner, etc_group, 0o644, role="upstreams.toml"),
        PermRow(paths.hardware_json(), etc_owner, etc_group, 0o644, role="hardware.json"),
        PermRow(paths.openwebui_env(), etc_owner, etc_group, 0o600, role="openwebui.env"),
        PermRow(
            paths.slots_config_dir(),
            etc_owner,
            etc_group,
            slots_dir_mode,
            glob="*.toml",
            child_mode=0o600,  # slots/*.toml are 0600 on disk (owner flips with the dir)
            optional=False,
            role="slots/ (+ *.toml)",
        ),
        # agents/ is the dashboard-only Hermes world — pinned root:root (#843),
        # under the flip too: the API only reads it.
        PermRow(paths.agents_config_dir(), "root", "root", 0o755, role="agents/"),
        # ── /var/lib/hal0 — mutable state (already service-owned) ──────────────
        PermRow(
            var_lib,
            state_owner,
            service_group,
            0o2775,
            optional=False,
            role="/var/lib/hal0 (state root)",
        ),
        PermRow(
            paths.var_lib() / ".hermes",
            state_owner,
            service_group,
            0o700,
            role="HERMES_HOME",
        ),
        # secrets/ stays root:root even under the flip: systemd reads the
        # EnvironmentFile here AS ROOT before dropping to the service user, so it
        # must not be service-writable (hardened-model decision).
        PermRow(var_lib / "secrets", "root", "root", 0o755, role="secrets/"),
        # ── /var/log/hal0 ─────────────────────────────────────────────────────
        PermRow(var_log, "hal0", "hal0", 0o755, role="/var/log/hal0"),
    ]


# ── observation (the ownership snapshot) ──────────────────────────────────────


@dataclass(frozen=True)
class PermObservation:
    """A path's current ownership snapshot — the analogue of ``FileState``.

    ``exists is False`` means the path is absent; ``owner``/``group``/``mode``
    are then ``None``.
    """

    path: Path
    exists: bool
    owner: str | None
    group: str | None
    mode: int | None


def _owner_name(uid: int) -> str | None:
    try:
        return pwd.getpwuid(uid).pw_name
    except (KeyError, OSError):
        return None


def _group_name(gid: int) -> str | None:
    try:
        return grp.getgrgid(gid).gr_name
    except (KeyError, OSError):
        return None


def observe(path: Path) -> PermObservation:
    """Snapshot one path's ownership + permission bits, or absence."""
    try:
        st = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return PermObservation(path=path, exists=False, owner=None, group=None, mode=None)
    return PermObservation(
        path=path,
        exists=True,
        owner=_owner_name(st.st_uid),
        group=_group_name(st.st_gid),
        mode=stat_mod.S_IMODE(st.st_mode),
    )


# ── plan (compute-only) ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class PermDiff:
    """The declared target for one concrete path, plus its current observation.

    ``changed`` is true only when the path EXISTS and at least one of owner /
    group / mode differs from the declared target. An absent path is never
    "changed" (nothing to chown); it is surfaced separately as ``absent``.
    """

    path: Path
    before: PermObservation
    owner: str
    group: str
    mode: int
    role: str

    @property
    def changed(self) -> bool:
        if not self.before.exists:
            return False
        return (
            self.before.owner != self.owner
            or self.before.group != self.group
            or (self.before.mode is not None and self.before.mode != self.mode)
        )


@dataclass(frozen=True)
class OwnershipPlan:
    """Compute-only result of planning the ownership table against disk.

    ``diffs`` covers every concrete path the table addresses (glob rows expand
    to one diff per match). The analogue of ``slot_config.ChangeSet``.
    """

    diffs: tuple[PermDiff, ...]

    @property
    def changed(self) -> bool:
        return any(d.changed for d in self.diffs)

    @property
    def drifted(self) -> tuple[PermDiff, ...]:
        return tuple(d for d in self.diffs if d.changed)


def _expand_row(row: PermRow) -> list[tuple[Path, PermRow]]:
    """Expand a glob row to one (path, row) per match; identity for plain rows."""
    if row.glob is None:
        return [(row.target, row)]
    if not row.target.is_dir():
        return [(row.target, row)]  # the dir itself (absent/optional handled in plan)
    out: list[tuple[Path, PermRow]] = [(row.target, row)]
    child_mode = row.child_mode if row.child_mode is not None else row.mode
    for child in sorted(row.target.glob(row.glob)):
        out.append(
            (
                child,
                replace(
                    row,
                    target=child,
                    mode=child_mode,
                    glob=None,
                    child_mode=None,
                    role=f"{row.label} :: {child.name}",
                ),
            )
        )
    return out


def plan(
    table: Iterable[PermRow] | None = None,
    *,
    observe_fn: Callable[[Path], PermObservation] = observe,
) -> OwnershipPlan:
    """Snapshot disk and compute the per-path ownership diff. Writes NOTHING.

    ``observe_fn`` is injected so the plan/diff logic is unit-tested without a
    real filesystem. Glob rows expand against the live directory.
    """
    rows = list(table) if table is not None else ownership_table()
    diffs: list[PermDiff] = []
    for row in rows:
        for concrete, eff in _expand_row(row):
            before = observe_fn(concrete)
            diffs.append(
                PermDiff(
                    path=concrete,
                    before=before,
                    owner=eff.owner,
                    group=eff.group,
                    mode=eff.mode,
                    role=eff.label,
                )
            )
    return OwnershipPlan(diffs=tuple(diffs))


# ── commit / revert ───────────────────────────────────────────────────────────


def _apply_one(
    path: Path,
    owner: str,
    group: str,
    mode: int,
    *,
    chown: Callable[[str, int, int], None],
    chmod: Callable[[str, int], None],
) -> None:
    """Resolve owner/group to ids and apply chown + chmod to one path."""
    uid = pwd.getpwnam(owner).pw_uid
    gid = grp.getgrnam(group).gr_gid
    chown(str(path), uid, gid)
    chmod(str(path), mode)


def commit(
    plan_: OwnershipPlan,
    *,
    chown: Callable[[str, int, int], None] = os.chown,
    chmod: Callable[[str, int], None] = os.chmod,
) -> list[Path]:
    """Apply every drifted diff, rolling back on failure. Returns paths changed.

    Mirrors ``SlotConfigStore.commit``: each path is chowned+chmodded in order;
    if a later path fails, every already-applied path is restored to its
    ``before`` snapshot and the original exception re-raised — disk is never
    left half-reconciled. Absent paths are skipped (nothing to own).

    Requires privilege to chown to a different user; raises ``PermissionError``
    otherwise (the ``doctor perms --fix`` caller is root-gated, as today).
    """
    applied: list[PermDiff] = []
    for d in plan_.drifted:
        try:
            _apply_one(d.path, d.owner, d.group, d.mode, chown=chown, chmod=chmod)
        except BaseException:
            for prior in reversed(applied):
                b = prior.before
                if b.exists and b.owner and b.group and b.mode is not None:
                    with contextlib.suppress(OSError, KeyError):
                        _apply_one(b.path, b.owner, b.group, b.mode, chown=chown, chmod=chmod)
            raise
        applied.append(d)
    return [d.path for d in applied]


# ── audit (doctor perms) ──────────────────────────────────────────────────────


def audit_rows(plan_: OwnershipPlan) -> list[dict[str, str]]:
    """Render an :class:`OwnershipPlan` as ``doctor``-style audit rows.

    Uses the same ``ok`` / ``drift`` / ``absent`` status vocabulary as
    :func:`hal0.cli.doctor_commands.check_hermes_ownership` so the renderer is
    shared.
    """
    rows: list[dict[str, str]] = []
    for d in plan_.diffs:
        if not d.before.exists:
            rows.append(
                {
                    "path": str(d.path),
                    "label": d.role,
                    "status": "absent",
                    "detail": "not present",
                }
            )
            continue
        want = f"{d.owner}:{d.group} {d.mode:04o}"
        have = f"{d.before.owner or '?'}:{d.before.group or '?'} {(d.before.mode or 0):04o}"
        if d.changed:
            rows.append(
                {
                    "path": str(d.path),
                    "label": d.role,
                    "status": "drift",
                    "detail": f"is {have}, want {want}",
                }
            )
        else:
            rows.append({"path": str(d.path), "label": d.role, "status": "ok", "detail": have})
    return rows


__all__ = [
    "OwnershipPlan",
    "PermDiff",
    "PermObservation",
    "PermRow",
    "audit_rows",
    "commit",
    "observe",
    "ownership_table",
    "plan",
]

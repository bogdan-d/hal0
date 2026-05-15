"""Installer helper for the hal0-slot@.service template unit.

Phase 1 deliverable: ship the systemd template that SlotManager targets.

The template lives in ``packaging/systemd/hal0-slot@.service`` in the
repo and is installed to ``/etc/systemd/system/hal0-slot@.service`` on
the host.  Per-slot drop-ins (rendered by
``hal0.slots.unit_template.render_override``) provide the concrete
ExecStart; this template is just the structural skeleton.

Not invoked from app lifespan — this is installer territory.  The
shell installer (``installer/install.sh``) may call into here, but the
function is also safe to call from a CLI sub-command or one-off repair
script.

See:
  - PLAN.md §2 (deployment model — template unit + drop-ins)
  - PLAN.md §7 (installer)
  - src/hal0/slots/unit_template.py (drop-in renderer)
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


# Repo-relative source path for the template unit.  Resolved against the
# package's ``hal0`` location so a wheel/editable install both work:
#   <repo>/src/hal0/installer/template_unit.py  →  <repo>/packaging/systemd/...
_DEFAULT_SRC = (
    Path(__file__).resolve().parents[3] / "packaging" / "systemd" / "hal0-slot@.service"
)

#: Production install path for the template unit.
DEFAULT_DEST = Path("/etc/systemd/system/hal0-slot@.service")


def install_template_unit(
    *,
    src: Path | None = None,
    dest: Path | None = None,
    daemon_reload: bool = True,
    use_sudo: bool | None = None,
) -> Path:
    """Install ``hal0-slot@.service`` and reload systemd.

    Copies ``packaging/systemd/hal0-slot@.service`` to
    ``/etc/systemd/system/hal0-slot@.service`` and runs
    ``systemctl daemon-reload``.

    Args:
        src: Source path.  Defaults to the bundled
            ``packaging/systemd/hal0-slot@.service`` resolved relative to
            the ``hal0`` package install location.
        dest: Destination path.  Defaults to
            ``/etc/systemd/system/hal0-slot@.service``.
        daemon_reload: When True (default), run
            ``systemctl daemon-reload`` after copying.
        use_sudo: When True, prefix install commands with ``sudo``.  When
            None (default), auto-detect: use sudo if the destination
            directory is not writable by the current user.

    Returns:
        The destination path the unit was written to.

    Raises:
        FileNotFoundError: If the source file does not exist.
        subprocess.CalledProcessError: If the copy or daemon-reload
            command fails.
    """
    src_path = Path(src) if src is not None else _DEFAULT_SRC
    dst_path = Path(dest) if dest is not None else DEFAULT_DEST

    if not src_path.is_file():
        raise FileNotFoundError(
            f"hal0-slot@.service source missing: {src_path}. "
            "Run from a checked-out repo or reinstall the hal0 package."
        )

    if use_sudo is None:
        # Heuristic: if the destination directory exists and is writable,
        # skip sudo.  Otherwise prepend it.  Callers can override.
        parent = dst_path.parent
        use_sudo = not (parent.exists() and parent.is_dir() and _is_writable(parent))

    log.info(
        "installing hal0-slot@.service",
        extra={"src": str(src_path), "dst": str(dst_path), "sudo": use_sudo},
    )

    _run(["install", "-m", "0644", str(src_path), str(dst_path)], use_sudo=use_sudo)

    if daemon_reload:
        log.info("running systemctl daemon-reload")
        _run(["systemctl", "daemon-reload"], use_sudo=use_sudo)

    return dst_path


def _is_writable(path: Path) -> bool:
    """Return True if ``path`` is writable by the current process."""
    import os

    return os.access(path, os.W_OK)


def _run(argv: list[str], *, use_sudo: bool) -> None:
    """Run ``argv`` synchronously, optionally under sudo.

    Raises ``subprocess.CalledProcessError`` on non-zero exit and
    ``FileNotFoundError`` if ``sudo`` is requested but not installed.
    """
    if use_sudo:
        if shutil.which("sudo") is None:
            raise FileNotFoundError(
                "sudo is required to write to system paths but is not installed. "
                "Re-run as root or pass use_sudo=False with an alternate dest."
            )
        argv = ["sudo", *argv]
    subprocess.run(argv, check=True)


__all__ = ["DEFAULT_DEST", "install_template_unit"]

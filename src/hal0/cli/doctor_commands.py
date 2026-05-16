"""CLI implementation for ``hal0 doctor``.

Shells out to ``installer/lib/preflight.sh`` (the same script
``installer/install.sh`` sources for its pre-install checks) so the
operator can re-run the full preflight battery post-install without
touching the installer.

Locating the script:

* ``HAL0_PREFLIGHT_SH`` env var wins, when set — useful for tests and
  for the eventual FHS install layout (``/opt/hal0/installer/lib/...``).
* Otherwise we walk up from this module's path to find a sibling
  ``installer/lib/preflight.sh``. ``install.sh`` does an editable
  ``pip install -e <repo>`` today, so ``Path(hal0.__file__).parents[2]``
  resolves to the repo root in every install.sh-produced environment.

The command preserves the script's exit code so it composes with other
shell tooling (``hal0 doctor && hal0 status``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

import hal0

app = typer.Typer(
    name="doctor",
    help="Re-run the installer's pre-flight checks against the live host.",
    no_args_is_help=False,
)

console = Console()


def _locate_preflight() -> Path | None:
    """Find ``installer/lib/preflight.sh`` for the current install.

    Returns ``None`` when the script is missing — the caller surfaces a
    clear error rather than a confused subprocess failure. We check the
    explicit env-var first, then derive from the package location.
    """
    override = os.environ.get("HAL0_PREFLIGHT_SH", "").strip()
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None

    # In an editable install, ``hal0.__file__`` is
    # ``<repo>/src/hal0/__init__.py``; parents[2] is the repo root.
    # In a future wheel-style install the file may live under
    # ``site-packages/hal0/`` with no repo neighbours — at that point
    # the install layout will need to bundle ``installer/lib/`` and
    # set ``HAL0_PREFLIGHT_SH``.
    try:
        repo_root = Path(hal0.__file__).resolve().parents[2]
    except (AttributeError, IndexError):
        return None
    candidate = repo_root / "installer" / "lib" / "preflight.sh"
    return candidate if candidate.is_file() else None


@app.callback(invoke_without_command=True)
def doctor(
    plain: bool = typer.Option(
        False,
        "--plain",
        help="Force ASCII-only output (sets HAL0_PLAIN=1 for the child shell).",
    ),
    ports: str | None = typer.Option(
        None,
        "--ports",
        help="Space-separated TCP ports for the port collision check (default: '8080 3001').",
    ),
) -> None:
    """Re-run pre-flight checks (systemd, python, docker, disk, ports)."""
    preflight = _locate_preflight()
    if preflight is None:
        console.print(
            "[red]✗[/red]  Could not locate installer/lib/preflight.sh.\n"
            "    Set HAL0_PREFLIGHT_SH=/path/to/preflight.sh or re-install"
            " from a repo checkout."
        )
        raise typer.Exit(2)

    bash = shutil.which("bash")
    if bash is None:
        console.print("[red]✗[/red]  bash not found on PATH — required to run preflight.sh")
        raise typer.Exit(2)

    env = os.environ.copy()
    if plain:
        env["HAL0_PLAIN"] = "1"
    if ports is not None:
        env["HAL0_DOCTOR_PORTS"] = ports

    try:
        result = subprocess.run(
            [bash, str(preflight)],
            env=env,
            check=False,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    except OSError as exc:  # pragma: no cover — bash missing is caught above
        console.print(f"[red]✗[/red]  failed to exec bash: {exc}")
        raise typer.Exit(2) from exc

    # Preserve the script's exit code verbatim so chained shells see a
    # non-zero on the first failed check.
    raise typer.Exit(result.returncode)

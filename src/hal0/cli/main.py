"""hal0 CLI entry point.

Entry point declared in pyproject.toml:
    [project.scripts]
    hal0 = "hal0.cli.main:app"
"""

from __future__ import annotations

from enum import StrEnum

import typer
import uvicorn
from rich.console import Console

import hal0
from hal0.cli._shared import NOT_IMPLEMENTED
from hal0.cli.config_commands import app as config_app
from hal0.cli.model_commands import app as model_app
from hal0.cli.slot_commands import app as slot_app

console = Console()

# ---------------------------------------------------------------------------
# Root app
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="hal0",
    help="hal0 — open-source home AI inference platform.",
    no_args_is_help=True,
    add_completion=True,
)

# Mount sub-apps
app.add_typer(slot_app, name="slot")
app.add_typer(model_app, name="model")
app.add_typer(config_app, name="config")


# ---------------------------------------------------------------------------
# --version callback
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"hal0 {hal0.__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        help="Print version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """hal0 — open-source home AI inference platform."""


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


@app.command()
def status() -> None:
    """Show system and slot summary."""
    # Phase 1: GET _api_base() + "/api/status" and render a rich table.
    console.print(NOT_IMPLEMENTED)


@app.command()
def probe() -> None:
    """Re-run hardware detection and update hardware.json."""
    # Phase 1: POST _api_base() + "/api/hardware/probe"
    console.print(NOT_IMPLEMENTED)


# ---------------------------------------------------------------------------
# hal0 update
# ---------------------------------------------------------------------------


class UpdateChannel(StrEnum):
    stable = "stable"
    nightly = "nightly"


@app.command()
def update(
    channel: UpdateChannel | None = typer.Option(
        None,
        "--channel",
        help="Update channel (stable or nightly).",
    ),
    check: bool = typer.Option(False, "--check", help="Only check for updates, do not apply."),
    rollback: bool = typer.Option(False, "--rollback", help="Roll back to the previous version."),
) -> None:
    """Check for or apply a hal0 update, or roll back to the previous version."""
    # Phase 5: hit /api/updates/{check,pull,rollback} per flag
    console.print(NOT_IMPLEMENTED)


# ---------------------------------------------------------------------------
# hal0 serve  (Phase 0 — the only command that actually does something)
# ---------------------------------------------------------------------------


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host for the hal0 API."),
    port: int = typer.Option(8080, "--port", help="Bind port for the hal0 API."),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload (dev mode)."),
) -> None:
    """Start the hal0 API server (used by hal0-api.service)."""
    console.print(f"Starting hal0 API on [bold]{host}:{port}[/bold]")
    uvicorn.run("hal0.api:app", host=host, port=port, reload=reload)


# ---------------------------------------------------------------------------
# hal0 uninstall
# ---------------------------------------------------------------------------


@app.command()
def uninstall(
    keep_data: bool = typer.Option(
        False,
        "--keep-data",
        help="Preserve /var/lib/hal0/ (model cache, openwebui state, slot data).",
    ),
) -> None:
    """Uninstall hal0 from this system."""
    # Phase 5: orchestrate systemctl stop/disable + dir removal
    console.print(NOT_IMPLEMENTED)

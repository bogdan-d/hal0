"""hal0 CLI entry point.

Entry point declared in pyproject.toml:
    [project.scripts]
    hal0 = "hal0.cli.main:app"
"""

from __future__ import annotations

import json as jsonlib

import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

import hal0
from hal0.cli._shared import (
    NOT_IMPLEMENTED,
    CliApiError,
    _api_base,
    _api_unreachable,
    api_get,
    api_post,
    die,
)
from hal0.cli.config_commands import app as config_app
from hal0.cli.model_commands import app as model_app
from hal0.cli.slot_commands import app as slot_app
from hal0.cli.update_commands import update as _update_impl

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
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    try:
        st = api_get("/api/status")
        slots = api_get("/api/slots")
        ups = api_get("/api/upstreams")
    except CliApiError as exc:
        die(str(exc))
        return
    console.print(
        Panel(
            f"[bold]{st.get('name', 'hal0')}[/bold] v{st.get('version', '?')}  "
            f"· slots={len(slots)} · upstreams={len(ups)}",
            border_style="cyan",
        )
    )
    table = Table(title="Slots")
    table.add_column("Name", style="bold")
    table.add_column("State")
    table.add_column("Model")
    table.add_column("Port", justify="right")
    for s in slots:
        table.add_row(
            s.get("name", "—"),
            s.get("status", "—"),
            s.get("model") or s.get("model_id") or "—",
            str(s.get("port") or "—"),
        )
    console.print(table)


@app.command()
def probe() -> None:
    """Re-run hardware detection and update hardware.json."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    try:
        hw = api_post("/api/hardware/probe")
    except CliApiError as exc:
        die(str(exc))
        return
    summary = {
        "cpu": hw.get("cpu_name"),
        "ram_mb": hw.get("ram_mb"),
        "unified_memory_mb": hw.get("unified_memory_mb"),
        "gpu": hw.get("gpu_name"),
        "gtt_total_mb": hw.get("gtt_total_mb"),
        "vram_total_mb": hw.get("vram_total_mb"),
        "npu": hw.get("npu_name"),
    }
    console.print(
        Panel(
            Syntax(
                jsonlib.dumps(summary, indent=2),
                "json",
                theme="ansi_dark",
                background_color="default",
            ),
            title="hardware probe",
            border_style="cyan",
        )
    )


# ---------------------------------------------------------------------------
# hal0 update — real implementation lives in hal0.cli.update_commands.
# Registered via app.command() so the function's typer.Options surface.
# ---------------------------------------------------------------------------

app.command(name="update")(_update_impl)


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

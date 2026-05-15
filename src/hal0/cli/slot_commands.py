"""hal0 slot subcommands — thin HTTP client to the hal0 API."""

from __future__ import annotations

from enum import StrEnum

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hal0.cli._shared import NOT_IMPLEMENTED, _api_base, _api_unreachable

app = typer.Typer(help="Manage inference slots.")
console = Console()

_PHASE_NOTE = "[not implemented yet — Phase 1: see PLAN.md §13]"


class SlotBackend(StrEnum):
    """Backends valid for a slot (mirrors PLAN.md §1 provider list)."""

    llama_server = "llama_server"
    flm = "flm"
    moonshine = "moonshine"
    kokoro = "kokoro"


@app.command("list")
def slot_list() -> None:
    """List all configured slots and their current state."""
    url = _api_base()
    if _api_unreachable(url):
        return
    # NOTE: Phase 0 stub — real impl calls GET /api/slots and renders a Table.
    table = Table(title="Slots")
    table.add_column("Name")
    table.add_column("State")
    table.add_column("Model")
    table.add_column("Port")
    console.print(table)
    console.print(NOT_IMPLEMENTED)


@app.command("load")
def slot_load(
    name: str = typer.Argument(..., help="Slot name (e.g. primary)"),
    model: str | None = typer.Option(
        None, "--model", "-m", help="Model ref to assign before loading"
    ),
) -> None:
    """Load a slot (optionally assign a model first)."""
    url = _api_base()
    if _api_unreachable(url):
        return
    console.print(NOT_IMPLEMENTED)


@app.command("unload")
def slot_unload(
    name: str = typer.Argument(..., help="Slot name to unload"),
) -> None:
    """Unload a running slot gracefully."""
    url = _api_base()
    if _api_unreachable(url):
        return
    console.print(NOT_IMPLEMENTED)


@app.command("restart")
def slot_restart(
    name: str = typer.Argument(..., help="Slot name to restart"),
) -> None:
    """Restart a slot (unload then load)."""
    url = _api_base()
    if _api_unreachable(url):
        return
    console.print(NOT_IMPLEMENTED)


@app.command("swap")
def slot_swap(
    name: str = typer.Argument(..., help="Slot name to swap"),
    model: str = typer.Option(..., "--model", "-m", help="Model ref to swap in"),
) -> None:
    """Hot-swap the model in a running slot."""
    url = _api_base()
    if _api_unreachable(url):
        return
    console.print(NOT_IMPLEMENTED)


@app.command("logs")
def slot_logs(
    name: str = typer.Argument(..., help="Slot name whose logs to stream"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream logs (SSE tail)"),
) -> None:
    """Print or follow logs for a slot."""
    url = _api_base()
    if _api_unreachable(url):
        return
    console.print(NOT_IMPLEMENTED)


# ---------------------------------------------------------------------------
# CRUD: create / edit / delete / show
# ---------------------------------------------------------------------------


@app.command("create")
def slot_create(
    name: str = typer.Argument(..., help="Slot name (e.g. primary, embed, stt)"),
    backend: SlotBackend = typer.Option(
        ...,
        "--backend",
        "-b",
        help="Provider backend for the slot.",
        case_sensitive=False,
    ),
    model: str = typer.Option(..., "--model", "-m", help="Initial model ref to assign."),
    port: int | None = typer.Option(
        None,
        "--port",
        "-p",
        help="Slot port (default: auto-assign next free port in 8081-8099).",
        min=1024,
        max=65535,
    ),
    ctx_size: int | None = typer.Option(
        None,
        "--ctx-size",
        help="Context window size in tokens (default: backend's preferred value).",
        min=128,
    ),
) -> None:
    """Create a new slot config (POST /api/slots)."""
    url = _api_base()
    if _api_unreachable(url):
        return
    # NOTE: Phase 1 — POST /api/slots with {name, backend, model, port, ctx_size}.
    # 409 on duplicate name; 400 on invalid backend/model; 201 on success.
    console.print(NOT_IMPLEMENTED)


@app.command("edit")
def slot_edit(
    name: str = typer.Argument(..., help="Slot name to edit"),
    model: str | None = typer.Option(None, "--model", "-m", help="New model ref."),
    port: int | None = typer.Option(
        None,
        "--port",
        "-p",
        help="New slot port.",
        min=1024,
        max=65535,
    ),
    ctx_size: int | None = typer.Option(
        None,
        "--ctx-size",
        help="New context window size in tokens.",
        min=128,
    ),
    backend: SlotBackend | None = typer.Option(
        None,
        "--backend",
        "-b",
        help="New provider backend.",
        case_sensitive=False,
    ),
) -> None:
    """Update one or more slot config fields (PUT /api/slots/{name}/config)."""
    url = _api_base()
    if _api_unreachable(url):
        return
    # NOTE: Phase 1 — collect provided fields into a dict, PUT only that subset.
    # If nothing was provided, exit with a helpful "no fields to update" error.
    if model is None and port is None and ctx_size is None and backend is None:
        console.print(
            "[bold yellow]No fields provided.[/bold yellow]  "
            "Pass at least one of --model, --port, --ctx-size, --backend."
        )
        raise typer.Exit(code=2)
    console.print(NOT_IMPLEMENTED)


@app.command("delete")
def slot_delete(
    name: str = typer.Argument(..., help="Slot name to delete"),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip the confirmation prompt.",
    ),
) -> None:
    """Delete a slot (DELETE /api/slots/{name})."""
    url = _api_base()
    if _api_unreachable(url):
        return
    if not force:
        # NOTE: typer.confirm aborts with exit code 1 on negative response.
        typer.confirm(
            f"Delete slot {name!r}? This stops the unit and removes its config.",
            abort=True,
        )
    # NOTE: Phase 1 — DELETE /api/slots/{name}; surface 404 as friendly error.
    console.print(NOT_IMPLEMENTED)


@app.command("show")
def slot_show(
    name: str = typer.Argument(..., help="Slot name to inspect"),
) -> None:
    """Show full slot config + status as a rich panel (GET /api/slots/{name})."""
    url = _api_base()
    if _api_unreachable(url):
        return
    # NOTE: Phase 1 — GET /api/slots/{name} returns {config: {...}, status: {...}}.
    # Render config block, status block, and recent state transitions in a Panel.
    panel = Panel(
        NOT_IMPLEMENTED,
        title=f"slot: {name}",
        border_style="cyan",
    )
    console.print(panel)

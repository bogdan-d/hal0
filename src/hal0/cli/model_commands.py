"""hal0 model subcommands — thin HTTP client to the hal0 API."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from hal0.cli._shared import NOT_IMPLEMENTED, _api_base, _api_unreachable

app = typer.Typer(help="Manage the local model registry.")
console = Console()


@app.command("list")
def model_list() -> None:
    """List all models in the local registry."""
    url = _api_base()
    if _api_unreachable(url):
        return
    # NOTE: Phase 0 stub — real impl calls GET /api/models and renders a Table.
    table = Table(title="Models")
    table.add_column("Ref")
    table.add_column("Size")
    table.add_column("Assigned Slot")
    table.add_column("Status")
    console.print(table)
    console.print(NOT_IMPLEMENTED)


@app.command("pull")
def model_pull(
    ref: str = typer.Argument(..., help="HuggingFace ref or curated alias (e.g. qwen3-4b)"),
) -> None:
    """Download a model into the local registry."""
    url = _api_base()
    if _api_unreachable(url):
        return
    console.print(NOT_IMPLEMENTED)


@app.command("rm")
def model_rm(
    ref: str = typer.Argument(..., help="Model ref to remove from the registry"),
) -> None:
    """Remove a model from the local registry."""
    url = _api_base()
    if _api_unreachable(url):
        return
    console.print(NOT_IMPLEMENTED)


@app.command("assign")
def model_assign(
    ref: str = typer.Argument(..., help="Model ref to assign"),
    slot: str = typer.Option(..., "--slot", "-s", help="Slot name to assign the model to"),
) -> None:
    """Assign a model to a slot (does not load the slot)."""
    url = _api_base()
    if _api_unreachable(url):
        return
    console.print(NOT_IMPLEMENTED)

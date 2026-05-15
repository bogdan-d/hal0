"""hal0 model subcommands — thin HTTP client to the hal0 API."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from hal0.cli._shared import (
    CliApiError,
    _api_base,
    _api_unreachable,
    api_delete,
    api_get,
    api_put,
    die,
)

app = typer.Typer(help="Manage the local model registry.")
console = Console()


def _fmt_size(b: int | None) -> str:
    if not b:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    n = float(b)
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{n:.1f}{units[i]}"


@app.command("list")
def model_list() -> None:
    """List all models in the local registry and from upstreams."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    try:
        data = api_get("/api/models")
    except CliApiError as exc:
        die(str(exc))
        return
    models = data.get("models", []) if isinstance(data, dict) else data
    table = Table(title=f"Models ({len(models)})")
    table.add_column("ID", style="bold")
    table.add_column("Name")
    table.add_column("Upstream")
    table.add_column("Size", justify="right")
    if not models:
        console.print("[dim]No models available.[/dim]")
        return
    for m in models:
        table.add_row(
            m.get("id", "—"),
            m.get("name") or m.get("id", "—"),
            m.get("upstream") or m.get("owned_by") or "—",
            _fmt_size(m.get("size_bytes")),
        )
    console.print(table)


@app.command("pull")
def model_pull(
    ref: str = typer.Argument(..., help="HuggingFace ref or curated alias (e.g. qwen3-4b)"),
) -> None:
    """Download a model into the local registry (Phase 1: not yet wired)."""
    console.print(
        f"[yellow]Pull is not yet implemented in the CLI[/yellow] — model {ref!r} not fetched.\n"
        "Drop the file into /var/lib/hal0/models/ then `hal0 model register <id> --path …`."
    )
    raise typer.Exit(1)


@app.command("register")
def model_register(
    model_id: str = typer.Argument(..., help="Model id, e.g. 'qwen3-4b-q4_k_m'"),
    path: str = typer.Option(..., "--path", "-p", help="Absolute path to the model file."),
    name: str = typer.Option("", "--name", help="Display name."),
    license_id: str = typer.Option("unknown", "--license", help="SPDX license id."),
) -> None:
    """Register a model that's already on disk into the local registry."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    payload = {
        "id": model_id,
        "path": path,
        "name": name or model_id,
        "license": license_id,
    }
    try:
        from hal0.cli._shared import api_post

        m = api_post("/api/models", json=payload)
    except CliApiError as exc:
        die(str(exc))
        return
    console.print(f"Registered [bold]{m.get('id', model_id)}[/bold] → {m.get('path', path)}")


@app.command("rm")
def model_rm(
    ref: str = typer.Argument(..., help="Model ref to remove from the registry"),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """Remove a model from the local registry."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    if not force:
        typer.confirm(f"Remove model {ref!r} from the registry?", abort=True)
    try:
        api_delete(f"/api/models/{ref}")
    except CliApiError as exc:
        die(str(exc))
        return
    console.print(f"Removed model [bold]{ref}[/bold] from the registry.")


@app.command("show")
def model_show(
    ref: str = typer.Argument(..., help="Model ref to inspect"),
) -> None:
    """Show a model's metadata."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    try:
        m = api_get(f"/api/models/{ref}")
    except CliApiError as exc:
        die(str(exc))
        return
    table = Table(show_header=False, title=m.get("id", ref))
    for k, v in m.items():
        table.add_row(k, str(v))
    console.print(table)


@app.command("assign")
def model_assign(
    ref: str = typer.Argument(..., help="Model ref to assign"),
    slot: str = typer.Option(..., "--slot", "-s", help="Slot name to assign the model to"),
) -> None:
    """Assign a model to a slot's default (does not load the slot)."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    try:
        api_put(f"/api/slots/{slot}/config", json={"model": {"default": ref}})
    except CliApiError as exc:
        die(str(exc))
        return
    console.print(f"Assigned [bold]{ref}[/bold] → slot [bold]{slot}[/bold]")

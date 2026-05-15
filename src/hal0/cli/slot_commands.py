"""hal0 slot subcommands — thin HTTP client to the hal0 API."""

from __future__ import annotations

import json as jsonlib
from enum import StrEnum
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from hal0.cli._shared import (
    CliApiError,
    _api_base,
    _api_unreachable,
    api_delete,
    api_get,
    api_patch,
    api_post,
    api_put,
    die,
)

app = typer.Typer(help="Manage inference slots.")
console = Console()


class SlotBackend(StrEnum):
    """Backends valid for a slot (mirrors PLAN.md §1 provider list)."""

    llama_server = "llama-server"
    flm = "flm"
    moonshine = "moonshine"
    kokoro = "kokoro"


_STATE_STYLES = {
    "ready": "bold green",
    "serving": "bold green",
    "running": "bold green",
    "warming": "yellow",
    "starting": "yellow",
    "idle": "cyan",
    "error": "bold red",
    "offline": "dim",
    "unloading": "dim",
}


def _fmt_state(state: str | None) -> str:
    if not state:
        return "[dim]—[/dim]"
    style = _STATE_STYLES.get(state, "white")
    return f"[{style}]{state}[/{style}]"


@app.command("list")
def slot_list() -> None:
    """List all configured slots and their current state."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    try:
        slots = api_get("/api/slots")
    except CliApiError as exc:
        die(str(exc))
        return
    table = Table(title="hal0 slots")
    table.add_column("Name", style="bold")
    table.add_column("State")
    table.add_column("Model")
    table.add_column("Backend")
    table.add_column("Port", justify="right")
    table.add_column("Kind", style="dim")
    if not slots:
        console.print("[dim]No slots configured.[/dim]")
        return
    for s in slots:
        table.add_row(
            s.get("name", "—"),
            _fmt_state(s.get("status") or s.get("state")),
            (s.get("model") or s.get("model_id") or "—") or "—",
            s.get("backend", "—") or "—",
            str(s.get("port") or "—"),
            s.get("kind", "—") or "—",
        )
    console.print(table)


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
        raise typer.Exit(1)
    try:
        body = {"model_id": model} if model else {}
        snap = api_post(f"/api/slots/{name}/load", json=body)
    except CliApiError as exc:
        die(str(exc))
        return
    console.print(
        f"Loaded [bold]{name}[/bold] → state={_fmt_state(snap.get('state'))} model={snap.get('model_id', '—')}"
    )


@app.command("unload")
def slot_unload(
    name: str = typer.Argument(..., help="Slot name to unload"),
) -> None:
    """Unload a running slot gracefully."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    try:
        snap = api_post(f"/api/slots/{name}/unload")
    except CliApiError as exc:
        die(str(exc))
        return
    console.print(f"Unloaded [bold]{name}[/bold] → state={_fmt_state(snap.get('state'))}")


@app.command("restart")
def slot_restart(
    name: str = typer.Argument(..., help="Slot name to restart"),
) -> None:
    """Restart a slot (unload then load)."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    try:
        snap = api_post(f"/api/slots/{name}/restart")
    except CliApiError as exc:
        die(str(exc))
        return
    console.print(f"Restarted [bold]{name}[/bold] → state={_fmt_state(snap.get('state'))}")


@app.command("swap")
def slot_swap(
    name: str = typer.Argument(..., help="Slot name to swap"),
    model: str = typer.Option(..., "--model", "-m", help="Model ref to swap in"),
) -> None:
    """Hot-swap the model in a running slot."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    try:
        snap = api_post(f"/api/slots/{name}/swap", json={"model_id": model})
    except CliApiError as exc:
        die(str(exc))
        return
    console.print(
        f"Swapped [bold]{name}[/bold] → {snap.get('model_id', model)} state={_fmt_state(snap.get('state'))}"
    )


@app.command("logs")
def slot_logs(
    name: str = typer.Argument(..., help="Slot name whose logs to stream"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream logs (SSE tail)"),
    lines: int = typer.Option(200, "--lines", "-n", min=1, max=5000),
) -> None:
    """Print or follow logs for a slot."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    if not follow:
        try:
            data = api_get(f"/api/slots/{name}/logs", params={"lines": lines})
        except CliApiError as exc:
            die(str(exc))
            return
        console.print(data.get("logs") or "[dim]no logs[/dim]")
        return

    # Stream SSE — line-buffered passthrough.
    try:
        with httpx.stream("GET", url + f"/api/slots/{name}/logs/stream", timeout=None) as r:
            for raw in r.iter_lines():
                if not raw or not raw.startswith("data:"):
                    continue
                payload = raw[5:].strip()
                try:
                    console.print(jsonlib.loads(payload))
                except ValueError:
                    console.print(payload)
    except (httpx.HTTPError, KeyboardInterrupt):
        return


@app.command("create")
def slot_create(
    name: str = typer.Argument(..., help="Slot name (e.g. primary, embed, stt)"),
    backend: SlotBackend = typer.Option(
        "llama-server",
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
    ctx_size: int = typer.Option(4096, "--ctx-size", min=128),
) -> None:
    """Create a new slot config (POST /api/slots)."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    body: dict[str, Any] = {
        "name": name,
        "backend": "vulkan",  # backend in the SlotConfig sense (hardware target)
        "provider": str(backend),
        "model": {"default": model, "context_size": ctx_size},
    }
    if port is not None:
        body["port"] = port
    else:
        # Best-effort: pick first free port in 8081-8099 by asking the API.
        try:
            existing = api_get("/api/slots")
            used = {int(s.get("port") or 0) for s in existing}
            for p in range(8081, 8100):
                if p not in used:
                    body["port"] = p
                    break
        except CliApiError:
            body["port"] = 8081
    try:
        snap = api_post("/api/slots", json=body)
    except CliApiError as exc:
        die(str(exc))
        return
    console.print(
        f"Created slot [bold]{name}[/bold] on port {snap.get('port')} (model={model})"
    )


@app.command("edit")
def slot_edit(
    name: str = typer.Argument(..., help="Slot name to edit"),
    model: str | None = typer.Option(None, "--model", "-m"),
    port: int | None = typer.Option(None, "--port", "-p", min=1024, max=65535),
    ctx_size: int | None = typer.Option(None, "--ctx-size", min=128),
    backend: SlotBackend | None = typer.Option(None, "--backend", "-b", case_sensitive=False),
) -> None:
    """Update one or more slot config fields (PUT /api/slots/{name}/config)."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    if model is None and port is None and ctx_size is None and backend is None:
        console.print(
            "[bold yellow]No fields provided.[/bold yellow]  "
            "Pass at least one of --model, --port, --ctx-size, --backend."
        )
        raise typer.Exit(code=2)

    payload: dict[str, Any] = {}
    if port is not None:
        payload["port"] = port
    if backend is not None:
        payload["provider"] = str(backend)
    if model is not None or ctx_size is not None:
        try:
            cfg = api_get(f"/api/slots/{name}/config")
        except CliApiError as exc:
            die(str(exc))
            return
        model_block = dict(cfg.get("model") or {})
        if model is not None:
            model_block["default"] = model
        if ctx_size is not None:
            model_block["context_size"] = ctx_size
        payload["model"] = model_block

    try:
        snap = api_put(f"/api/slots/{name}/config", json=payload)
    except CliApiError as exc:
        die(str(exc))
        return
    console.print(f"Updated [bold]{name}[/bold] → {snap.get('state', '—')}")


@app.command("delete")
def slot_delete(
    name: str = typer.Argument(..., help="Slot name to delete"),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """Delete a slot (DELETE /api/slots/{name})."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    if not force:
        typer.confirm(
            f"Delete slot {name!r}? This stops the unit and removes its config.",
            abort=True,
        )
    try:
        api_delete(f"/api/slots/{name}")
    except CliApiError as exc:
        die(str(exc))
        return
    console.print(f"Deleted slot [bold]{name}[/bold].")


@app.command("show")
def slot_show(
    name: str = typer.Argument(..., help="Slot name to inspect"),
) -> None:
    """Show full slot config + status (GET /api/slots/{name})."""
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)
    try:
        status = api_get(f"/api/slots/{name}")
    except CliApiError as exc:
        die(str(exc))
        return
    try:
        cfg = api_get(f"/api/slots/{name}/config")
    except CliApiError:
        cfg = None
    body = jsonlib.dumps({"status": status, "config": cfg}, indent=2)
    console.print(
        Panel(
            Syntax(body, "json", theme="ansi_dark", background_color="default"),
            title=f"slot: {name}",
            border_style="cyan",
        )
    )

"""hal0 config subcommands — thin HTTP client to the hal0 API."""

from __future__ import annotations

import typer
from rich.console import Console

from hal0.cli._shared import NOT_IMPLEMENTED, _api_base, _api_unreachable

app = typer.Typer(help="Inspect and manage hal0 configuration.")
console = Console()


@app.command("show")
def config_show() -> None:
    """Print the current hal0 configuration (hal0.toml + slot configs)."""
    url = _api_base()
    if _api_unreachable(url):
        return
    console.print(NOT_IMPLEMENTED)


@app.command("edit")
def config_edit() -> None:
    """Open hal0.toml in $EDITOR."""
    url = _api_base()
    if _api_unreachable(url):
        return
    console.print(NOT_IMPLEMENTED)


@app.command("migrate")
def config_migrate() -> None:
    """Apply pending schema migrations to /etc/hal0/."""
    url = _api_base()
    if _api_unreachable(url):
        return
    console.print(NOT_IMPLEMENTED)


@app.command("validate")
def config_validate() -> None:
    """Validate all config files against the current schema."""
    url = _api_base()
    if _api_unreachable(url):
        return
    console.print(NOT_IMPLEMENTED)

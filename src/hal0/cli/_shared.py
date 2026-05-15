"""Shared helpers for hal0 CLI modules."""

from __future__ import annotations

import os
import sys

from rich.console import Console

_console = Console(stderr=True)

NOT_IMPLEMENTED = "[not implemented yet — Phase N: see PLAN.md §13]"


def _api_base() -> str:
    """Return the hal0 API base URL, honouring HAL0_API_URL env override."""
    return os.environ.get("HAL0_API_URL", "http://127.0.0.1:8080").rstrip("/")


def _api_unreachable(url: str) -> bool:
    """Return True (and print a user-friendly error) if the API is not reachable.

    Phase 0: all commands are stubs so we never actually probe the socket.
    Real Phase-1 commands should call this before making any HTTP request.
    NOTE: In Phase 1 replace the stub body with a real TCP connect check, e.g.:
        import socket; s = socket.create_connection((...), timeout=1)
    """
    # Phase 0 stub: always report reachable so stubs can print their message.
    return False


def api_unreachable_exit(url: str) -> None:
    """Print an error and exit 1 when the API cannot be reached."""
    _console.print(
        f"[bold red]hal0 API not running on {url}.[/bold red]"
        "  Start it with: [bold]hal0 serve[/bold]"
    )
    sys.exit(1)

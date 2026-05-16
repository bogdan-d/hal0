"""CLI implementation for ``hal0 update``.

Thin client over the /api/updates/* surface. The CLI never invokes
``Updater`` directly — it goes through the daemon so the same code path
is exercised whether you trigger an update from the dashboard or the
shell. ``--restart-slots`` reaches around the API to ``systemctl`` after
a successful apply (see PLAN §9 + Team D brief).

Surface:
    hal0 update                 # check + apply if newer
    hal0 update --check         # check only
    hal0 update --rollback      # roll back to previous tree
    hal0 update --channel CH    # set channel (persists), then check
    hal0 update --target VER    # pin a specific version
    hal0 update --restart-slots # also bounce hal0-slot@*.service
"""

from __future__ import annotations

import shutil
import subprocess
import time
from enum import StrEnum

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hal0.cli._shared import (
    CliApiError,
    _api_base,
    _api_unreachable,
    api_get,
    api_post,
    api_put,
    die,
)

console = Console()


class UpdateChannel(StrEnum):
    stable = "stable"
    nightly = "nightly"


def _restart_slots() -> None:
    """Bounce every hal0-slot@*.service unit on this host.

    Reaches around the API directly because the dashboard's contract is
    that slot units are untouched across updates; this is an opt-in
    operator action (``--restart-slots``) per PLAN §9. Missing systemctl
    or non-root is reported but not fatal — the swap already succeeded.
    """
    systemctl = shutil.which("systemctl")
    if not systemctl:
        console.print("[yellow]systemctl not found; skipping slot restart.[/yellow]")
        return
    try:
        proc = subprocess.run(
            [systemctl, "restart", "hal0-slot@*.service"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        console.print(f"[yellow]slot restart errored: {exc}[/yellow]")
        return
    if proc.returncode != 0:
        console.print(
            f"[yellow]slot restart returned {proc.returncode}:[/yellow] {proc.stderr.strip()[:300]}"
        )
    else:
        console.print("[green]slot units restarted.[/green]")


def _print_check(body: dict) -> None:
    """Render the /api/updates/check response as a rich panel + table."""
    current = body.get("current", "?")
    latest = body.get("latest") or "—"
    channel = body.get("channel", "stable")
    available = body.get("update_available", False)

    status = "[green]update available[/green]" if available else "[dim]up to date[/dim]"
    console.print(
        Panel(
            f"[bold]hal0[/bold] {current}  →  {latest}  ({channel})  {status}",
            border_style="cyan",
        )
    )
    manifest = body.get("manifest") or {}
    if not isinstance(manifest, dict):
        manifest = {}
    if manifest:
        table = Table(show_header=False, box=None, padding=(0, 2))
        for key in ("released_at", "notes_url", "digest_sha256", "signer_identity"):
            val = manifest.get(key)
            if val:
                table.add_row(f"[dim]{key}[/dim]", str(val))
        console.print(table)


def _poll_job(job_id: str, *, timeout_s: float = 600.0) -> dict:
    """Poll /api/updates/status/<id> until it leaves the queued/running states."""
    deadline = time.monotonic() + timeout_s
    last_state: str | None = None
    while time.monotonic() < deadline:
        try:
            job = api_get(f"/api/updates/status/{job_id}")
        except CliApiError as exc:
            die(str(exc))
            return {}
        state = job.get("state")
        if state != last_state:
            console.print(f"[dim]· job {job_id} → {state}[/dim]")
            last_state = state
        if state in ("applied", "failed"):
            return job
        time.sleep(0.5)
    die(f"update job {job_id} timed out after {timeout_s:.0f}s")
    return {}


def update(
    channel: UpdateChannel | None = typer.Option(
        None,
        "--channel",
        help="Persist the update channel (stable | nightly), then check.",
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Only check for updates; do not apply.",
    ),
    rollback: bool = typer.Option(
        False,
        "--rollback",
        help="Roll back to the previous version recorded at /var/lib/hal0/hal0.previous.",
    ),
    target: str | None = typer.Option(
        None,
        "--target",
        help="Pin a specific version (e.g. v0.1.1). Overrides the latest manifest version.",
    ),
    restart_slots: bool = typer.Option(
        False,
        "--restart-slots",
        help="After a successful apply, also systemctl restart hal0-slot@*.service.",
    ),
) -> None:
    """Check for, apply, or roll back a hal0 update.

    This is a thin client over /api/updates/*; the actual swap happens in
    the daemon. Real progress comes from polling /api/updates/status/<id>.
    """
    url = _api_base()
    if _api_unreachable(url):
        raise typer.Exit(1)

    if channel is not None:
        try:
            api_put("/api/updates/channel", json={"channel": channel.value})
        except CliApiError as exc:
            die(str(exc))
            return
        console.print(f"[green]channel set to {channel.value}[/green]")

    if rollback:
        try:
            body = api_post("/api/updates/rollback")
        except CliApiError as exc:
            die(str(exc))
            return
        console.print(
            Panel(
                f"[green]rolled back[/green] ({body.get('channel', 'stable')})",
                border_style="green",
            )
        )
        return

    try:
        body = api_get("/api/updates/check")
    except CliApiError as exc:
        die(str(exc))
        return
    _print_check(body)

    if check:
        return

    target_version = (target or "").lstrip("v") or None
    if not body.get("update_available") and not target_version:
        console.print("[dim]nothing to apply.[/dim]")
        return

    try:
        job = api_post(
            "/api/updates/apply", json={"version": target_version} if target_version else {}
        )
    except CliApiError as exc:
        die(str(exc))
        return
    job_id = job.get("id")
    if not job_id:
        die("server returned no job id")
        return
    console.print(f"[cyan]apply job:[/cyan] {job_id}")

    final = _poll_job(job_id)
    state = final.get("state")
    if state == "applied":
        console.print(Panel("[green]update applied.[/green]", border_style="green"))
        if restart_slots:
            _restart_slots()
    else:
        err = final.get("error") or "unknown error"
        die(f"update {state}: {err}")

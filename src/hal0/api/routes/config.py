"""Config + URL discovery endpoints (mounted under /api/config).

The dashboard reads ``/api/config/urls`` on mount to discover the live
hostnames it should point its "Chat" button at.  The hal0 API itself
binds 0.0.0.0:8080 (PLAN §2 "public" tier) and OpenWebUI binds
0.0.0.0:3001, so the same hostname the dashboard is loaded from is the
right answer for both.

``openwebui_enabled`` reflects the unit's runtime state via ``systemctl
is-active hal0-openwebui`` (cheap — single subprocess, no parsing).
False on a host without systemd (CI / dev laptop), so the UI hides the
Chat link instead of leading users to a 404.
"""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Request

router = APIRouter()

# Default ports — these match what `hal0-api.service` and
# `hal0-openwebui.service` bind to.  The API port can be overridden via
# the HAL0_PORT env var that ``hal0-api.service`` sources from
# /etc/hal0/api.env; OpenWebUI's port is fixed at 3001 in the unit.
_DEFAULT_API_PORT = 8080
_OPENWEBUI_PORT = 3001

_OPENWEBUI_UNIT = "hal0-openwebui.service"


def _resolve_host(request: Request) -> str:
    """Pick the right hostname for the URLs we return.

    The user reaches the API at whatever hostname/IP they typed into
    their browser — exactly the hostname FastAPI sees in the request
    URL.  Mirroring that means the Chat link works whether the user
    typed ``http://hal0.local:8080``, ``http://10.0.1.230:8080``, or
    ``http://127.0.0.1:8080``.

    Falls back to ``127.0.0.1`` if the request has no hostname (rare —
    e.g. raw ASGI calls in tests).
    """
    hostname = request.url.hostname
    if not hostname:
        return "127.0.0.1"
    return hostname


def _api_port() -> int:
    """Return the API port the unit is bound to.

    ``HAL0_PORT`` is the same env var ``hal0-api.service`` consumes via
    ``EnvironmentFile=/etc/hal0/api.env``, so reading it here keeps the
    dashboard and the unit in lockstep without an extra config read.
    """
    raw = os.environ.get("HAL0_PORT", "").strip()
    if not raw:
        return _DEFAULT_API_PORT
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_API_PORT


async def _openwebui_is_active() -> bool:
    """Return True if ``hal0-openwebui.service`` is active under systemd.

    Uses ``systemctl is-active --quiet`` which exits 0 when the unit is
    active and non-zero otherwise.  Any failure (missing systemctl, the
    unit doesn't exist, permission denied) is treated as inactive so the
    dashboard hides the Chat link rather than dangling it at a 404.

    Async + short timeout so a wedged systemd never stalls the route.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "is-active",
            "--quiet",
            _OPENWEBUI_UNIT,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (FileNotFoundError, PermissionError, OSError):
        return False
    try:
        rc = await asyncio.wait_for(proc.wait(), timeout=2.0)
    except TimeoutError:
        proc.kill()
        return False
    return rc == 0


def _behind_proxy(request: Request) -> bool:
    """True when the request arrived through a reverse proxy.

    Detected via the proxy-set ``X-Forwarded-*`` headers (Caddy, Traefik,
    nginx all set at least one of these). A direct hit on hal0-api's
    bound port has none of them — that path keeps the legacy host:port
    URL shape so ``http://hal0.local:8080`` still produces a usable
    Chat link.
    """
    fwd = request.headers
    return any(fwd.get(h) for h in ("x-forwarded-host", "x-forwarded-proto", "x-forwarded-for"))


@router.get("/urls")
async def get_urls(request: Request) -> dict[str, object]:
    """Return the canonical URLs the dashboard should advertise.

    Response shape (stable contract — the dashboard depends on every key
    being present)::

        {
          "api":               "http://<host>:8080" | "https://<host>",
          "openwebui":         "http://<host>:3001" | "https://<host>/chat/",
          "openwebui_enabled": true | false,
        }

    When the request reached us via a reverse proxy (X-Forwarded-* set
    by Caddy/Traefik/nginx), the URLs are path-based so the auth proxy
    in front of us still gets to inject ``X-Forwarded-Email`` before
    the request lands on OpenWebUI. Without that, OpenWebUI's trusted-
    header mode rejects the request as "provider has not provided a
    trusted header".
    """
    host = _resolve_host(request)
    if _behind_proxy(request):
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
        forwarded_host = request.headers.get("x-forwarded-host") or host
        return {
            "api": f"{scheme}://{forwarded_host}",
            "openwebui": f"{scheme}://{forwarded_host}/chat/",
            "openwebui_enabled": await _openwebui_is_active(),
        }
    return {
        "api": f"http://{host}:{_api_port()}",
        "openwebui": f"http://{host}:{_OPENWEBUI_PORT}",
        "openwebui_enabled": await _openwebui_is_active(),
    }

"""Operator Board events-WS proxy — browser ⇄ Hermes kanban ``/events``.

The Hermes kanban events WS (SPEC §2.C / §6) polls ``task_events`` every 300ms
and pushes ``{"events": [...], "cursor": N}`` frames. Browsers cannot set
``Authorization`` on a WS upgrade, so Hermes takes the dashboard session token
as the ``?token=`` query param. This proxy:

* accepts the browser upgrade at ``/api/board/events`` (auth/accept handled by
  the route),
* resolves the Hermes session token SERVER-SIDE (never from the browser) and
  appends it as ``?token=`` on the upstream URL,
* threads the browser's ``since`` / ``board`` / ``tenant`` query params to the
  upstream so the cursor + board pin + tenant filter ride along,
* bidi-pumps text frames using the same shape as
  :func:`hal0.api.agents.chat_proxy._proxy_ws` (no progress coalescing — the
  kanban WS emits event batches, not a tool-progress stream).

On upstream connect failure the browser WS is closed with code ``1011`` so the
client's reconnect logic engages.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Awaitable, Callable
from urllib.parse import urlencode, urlsplit

import structlog
import websockets
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from hal0.board import (
    DEFAULT_BASE_URL,
    KANBAN_BASE_PATH,
    HermesKanbanClient,
    _default_session_token,
)

log = structlog.get_logger(__name__)

# Query params the browser is allowed to thread upstream (SPEC §6). The token
# is NOT in this set — it is server-resolved, never browser-supplied.
_PASSTHROUGH_QUERY = ("since", "board", "tenant")

WS_PING_INTERVAL_SECONDS = 20.0
WS_OPEN_TIMEOUT_SECONDS = 5.0


def _upstream_base_url() -> str:
    return os.environ.get("HERMES_DASHBOARD_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _http_to_ws(base_url: str) -> str:
    """Map an http(s) base URL to its ws(s) equivalent."""
    parts = urlsplit(base_url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    return f"{scheme}://{parts.netloc}"


def _build_upstream_url(browser_ws: WebSocket, *, token: str | None) -> str:
    """Compose the upstream events WS URL with token + passthrough query."""
    ws_base = _http_to_ws(_upstream_base_url())
    qs: dict[str, str] = {}
    if token:
        qs["token"] = token
    for key in _PASSTHROUGH_QUERY:
        val = browser_ws.query_params.get(key)
        if val is not None:
            qs[key] = val
    query = f"?{urlencode(qs)}" if qs else ""
    return f"{ws_base}{KANBAN_BASE_PATH}/events{query}"


async def _pump(
    source_recv: Callable[[], Awaitable[str]],
    sink_send: Callable[[str], Awaitable[None]],
    *,
    direction: str,
) -> None:
    """Read text frames from ``source_recv`` and write to ``sink_send``."""
    try:
        while True:
            frame = await source_recv()
            await sink_send(frame)
    except (WebSocketDisconnect, websockets.ConnectionClosed):
        log.debug("hal0.board_ws.pump_closed", direction=direction)
    except Exception as exc:  # pragma: no cover — defensive
        log.warning("hal0.board_ws.pump_error", direction=direction, error=str(exc))


async def _resolve_session_token(browser_ws: WebSocket, *, force_refresh: bool = False) -> str | None:
    """Resolve the Hermes session bearer for the upstream WS upgrade.

    Mirrors the REST path's resolution (``HermesKanbanClient._current_token``):
    an explicit ``HERMES_SESSION_TOKEN`` pin wins, otherwise the rotating
    per-process token is harvested from the dashboard HTML at ``/`` and cached.
    We route through the SHARED client on ``app.state.hermes_kanban`` so the
    env-pin + HTML-harvest + rotation cache live in exactly one place and a
    token refreshed by either surface (REST or WS) benefits both.

    The bare ``_default_session_token()`` env read — which the WS bridge used
    to use directly — only ever saw the env pin, so once deployments stopped
    pinning ``HERMES_SESSION_TOKEN`` and relied on the harvest, the events WS
    silently connected upstream with NO token and Hermes rejected the upgrade
    (403) while REST reads kept working. Falls back to the env resolver only
    when the shared client isn't wired (e.g. unit tests that stub app.state).
    """
    app = browser_ws.scope.get("app")
    client = getattr(getattr(app, "state", None), "hermes_kanban", None)
    if isinstance(client, HermesKanbanClient):
        return await client._current_token(force_refresh=force_refresh)
    return _default_session_token()


async def proxy_board_events(browser_ws: WebSocket) -> None:
    """Bridge an accepted browser WS to the upstream kanban events WS."""

    async def _connect(*, force_refresh: bool) -> websockets.WebSocketClientProtocol:
        token = await _resolve_session_token(browser_ws, force_refresh=force_refresh)
        url = _build_upstream_url(browser_ws, token=token)
        return await websockets.connect(
            url,
            ping_interval=WS_PING_INTERVAL_SECONDS,
            open_timeout=WS_OPEN_TIMEOUT_SECONDS,
        )

    try:
        upstream = await _connect(force_refresh=False)
    except Exception as exc:
        # The harvested per-process token may have rotated on a Hermes restart;
        # the upstream then rejects the upgrade (403). Drop the cached token,
        # re-harvest once, and retry — mirrors the REST client's 401 path. A
        # pinned env token re-reads identically, so this is a no-op there.
        log.info("hal0.board_ws.upstream_retry_after_refresh", error=str(exc))
        try:
            upstream = await _connect(force_refresh=True)
        except Exception as exc2:
            log.warning("hal0.board_ws.upstream_connect_failed", error=str(exc2))
            if browser_ws.application_state == WebSocketState.CONNECTED:
                await browser_ws.close(code=1011)
            return

    async def to_browser(raw: str) -> None:
        if browser_ws.application_state == WebSocketState.CONNECTED:
            await browser_ws.send_text(raw)

    async def from_upstream() -> str:
        raw = await upstream.recv()
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return raw

    async def from_browser() -> str:
        return await browser_ws.receive_text()

    async def to_upstream(raw: str) -> None:
        await upstream.send(raw)

    try:
        await asyncio.gather(
            _pump(from_upstream, to_browser, direction="upstream→browser"),
            _pump(from_browser, to_upstream, direction="browser→upstream"),
        )
    finally:
        with contextlib.suppress(Exception):
            await upstream.close()
        if browser_ws.application_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await browser_ws.close()


__all__ = ["_build_upstream_url", "_http_to_ws", "proxy_board_events"]

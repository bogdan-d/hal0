"""Tests for board_ws.py — URL builder + WS proxy framing.

Run targeted:
    PYTHONPATH=src .venv/bin/python -m pytest tests/board/test_board_ws.py -q
"""

from __future__ import annotations

import contextlib
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import QueryParams
from websockets.exceptions import ConnectionClosedOK

import hal0.api.routes.board_ws as board_ws_mod
from hal0.api.middleware.error_codes import install as install_errors
from hal0.api.routes import board
from hal0.api.routes.board_ws import _build_upstream_url, _http_to_ws
from hal0.board import HermesKanbanClient

# ── _http_to_ws ──────────────────────────────────────────────────────────────


def test_http_to_ws_http() -> None:
    assert _http_to_ws("http://127.0.0.1:9119") == "ws://127.0.0.1:9119"


def test_http_to_ws_https() -> None:
    assert _http_to_ws("https://hal0.example.com") == "wss://hal0.example.com"


def test_http_to_ws_strips_path() -> None:
    assert _http_to_ws("http://127.0.0.1:9119/some/path") == "ws://127.0.0.1:9119"


# ── _build_upstream_url ──────────────────────────────────────────────────────


class _FakeBrowserWS:
    def __init__(self, params: dict[str, str]) -> None:
        self.query_params = QueryParams(params)


def test_build_upstream_url_threads_passthrough(monkeypatch) -> None:
    monkeypatch.setenv("HERMES_DASHBOARD_BASE_URL", "http://127.0.0.1:9119")
    ws = _FakeBrowserWS({"since": "5", "board": "alpha", "tenant": "x"})
    url = _build_upstream_url(ws, token="TOK")
    parsed = urlsplit(url)
    assert parsed.scheme == "ws"
    assert parsed.netloc == "127.0.0.1:9119"
    assert parsed.path == "/api/plugins/kanban/events"
    qs = parse_qs(parsed.query)
    assert qs["token"] == ["TOK"]
    assert qs["since"] == ["5"]
    assert qs["board"] == ["alpha"]
    assert qs["tenant"] == ["x"]


def test_build_upstream_url_token_not_from_browser(monkeypatch) -> None:
    monkeypatch.setenv("HERMES_DASHBOARD_BASE_URL", "http://127.0.0.1:9119")
    ws = _FakeBrowserWS({"since": "0", "token": "EVIL_BROWSER_TOKEN"})
    url = _build_upstream_url(ws, token="SERVER_TOK")
    qs = parse_qs(urlsplit(url).query)
    assert qs.get("token") == ["SERVER_TOK"]
    assert "EVIL_BROWSER_TOKEN" not in qs.get("token", [])


def test_build_upstream_url_no_token(monkeypatch) -> None:
    monkeypatch.setenv("HERMES_DASHBOARD_BASE_URL", "http://127.0.0.1:9119")
    ws = _FakeBrowserWS({"since": "0"})
    url = _build_upstream_url(ws, token=None)
    qs = parse_qs(urlsplit(url).query)
    assert "token" not in qs
    assert qs["since"] == ["0"]


def test_build_upstream_url_https_becomes_wss(monkeypatch) -> None:
    monkeypatch.setenv("HERMES_DASHBOARD_BASE_URL", "https://hal0.example.com")
    url = _build_upstream_url(_FakeBrowserWS({}), token="T")
    assert url.startswith("wss://")


# ── WS proxy framing ─────────────────────────────────────────────────────────


class _FakeUpstreamWS:
    """Minimal async WS stub: yields frames then signals close."""

    def __init__(self, frames: list[str]) -> None:
        self._frames = list(frames)
        self.sent: list[str] = []

    async def recv(self) -> str:
        if self._frames:
            return self._frames.pop(0)
        raise ConnectionClosedOK(None, None)

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        pass


def _make_ws_app() -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    install_errors(app)
    app.include_router(board.router, prefix="/api/board")
    app.state.hermes_kanban = None  # WS proxy doesn't use it
    return app, TestClient(app, raise_server_exceptions=False)


def test_ws_proxy_forwards_upstream_frames(monkeypatch) -> None:
    frame = '{"events":[{"id":1}],"cursor":1}'
    fake_upstream = _FakeUpstreamWS([frame])
    connect_calls: list[str] = []

    async def fake_connect(url, **kwargs):
        connect_calls.append(url)
        return fake_upstream

    monkeypatch.setenv("HERMES_DASHBOARD_BASE_URL", "http://127.0.0.1:9119")
    monkeypatch.setenv("HERMES_SESSION_TOKEN", "TOK")
    # Patch ONLY connect so _pump keeps the real ConnectionClosed for except.
    monkeypatch.setattr(board_ws_mod.websockets, "connect", fake_connect)

    _app, client = _make_ws_app()
    received: list[str] = []
    with (
        client.websocket_connect("/api/board/events?since=0&board=alpha") as ws,
        contextlib.suppress(Exception),
    ):
        received.append(ws.receive_text())

    assert received == [frame]
    assert len(connect_calls) == 1
    qs = parse_qs(urlsplit(connect_calls[0]).query)
    assert qs.get("token") == ["TOK"]
    assert qs.get("since") == ["0"]
    assert qs.get("board") == ["alpha"]


_DASHBOARD_HTML = '<!doctype html><script>window.__HERMES_SESSION_TOKEN__="HARVESTED_TOK";</script>'


def _make_harvesting_client() -> HermesKanbanClient:
    """A real client whose MockTransport serves the dashboard HTML at ``/``.

    No env pin → the client harvests ``window.__HERMES_SESSION_TOKEN__`` from
    the HTML, exactly as it does against the live loopback dashboard.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, text=_DASHBOARD_HTML)
        return httpx.Response(200, json={})

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:9119"
    )
    return HermesKanbanClient(http_client=http)


def test_ws_proxy_harvests_token_when_env_unpinned(monkeypatch) -> None:
    """Regression: the events WS must use the HARVESTED session token, not just
    the ``HERMES_SESSION_TOKEN`` env pin.

    Production never pins the env var (the per-process token rotates), so the
    bridge relied on harvest for REST but sent NO token on the WS upgrade —
    Hermes answered 403 and live task events never reached the board. This
    asserts the upstream connect URL carries the harvested bearer with the env
    var explicitly unset.
    """
    monkeypatch.setenv("HERMES_DASHBOARD_BASE_URL", "http://127.0.0.1:9119")
    monkeypatch.delenv("HERMES_SESSION_TOKEN", raising=False)

    frame = '{"events":[{"id":1}],"cursor":1}'
    connect_calls: list[str] = []

    async def fake_connect(url, **kwargs):
        connect_calls.append(url)
        return _FakeUpstreamWS([frame])

    monkeypatch.setattr(board_ws_mod.websockets, "connect", fake_connect)

    app = FastAPI()
    install_errors(app)
    app.include_router(board.router, prefix="/api/board")
    app.state.hermes_kanban = _make_harvesting_client()
    client = TestClient(app, raise_server_exceptions=False)

    received: list[str] = []
    with (
        client.websocket_connect("/api/board/events?since=0") as ws,
        contextlib.suppress(Exception),
    ):
        received.append(ws.receive_text())

    assert received == [frame]
    assert len(connect_calls) == 1
    qs = parse_qs(urlsplit(connect_calls[0]).query)
    assert qs.get("token") == ["HARVESTED_TOK"]


def test_ws_proxy_upstream_connect_fails_closes_browser(monkeypatch) -> None:
    monkeypatch.setenv("HERMES_DASHBOARD_BASE_URL", "http://127.0.0.1:9119")
    monkeypatch.setenv("HERMES_SESSION_TOKEN", "TOK")

    async def failing_connect(url, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(board_ws_mod.websockets, "connect", failing_connect)

    _app, client = _make_ws_app()
    # Any WS close exception is acceptable — key is no unhandled server crash.
    with (
        contextlib.suppress(Exception),
        client.websocket_connect("/api/board/events?since=0") as ws,
    ):
        ws.receive_text()

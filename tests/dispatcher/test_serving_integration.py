"""Tests for Dispatcher.forward wiring SlotManager.serving().

Covers the dispatcher half of task #10 SERVING:

  - A slot-kind UpstreamCall flips the slot to SERVING for the duration
    of a non-streaming request, then back to READY.
  - A streaming request keeps the slot in SERVING until the response
    body iterator drains.
  - Remote-kind UpstreamCalls (empty ``slot_name``) leave the slot
    machinery alone.
  - Network errors release the serving counter so the slot doesn't get
    stuck in SERVING forever.
  - The single-flight prefetch path does NOT enter serving() — it only
    fetches /v1/models, never a real inference request.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from hal0.dispatcher.router import Dispatcher, UpstreamCall, UpstreamUnavailable

# ── tiny SlotManager stand-in ────────────────────────────────────────────────


class _RecordingSlotManager:
    """Minimal SlotManager surface — only what Dispatcher.forward touches.

    Records every enter/exit so tests can assert ordering without spinning
    up a real SlotManager (which would need a slot TOML + systemctl stubs).
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []  # (op, slot_name)
        self._counts: dict[str, int] = {}

    def serving(self, slot_name: str) -> _RecordingCtx:
        return _RecordingCtx(self, slot_name)

    def in_flight_count(self, slot_name: str) -> int:
        return self._counts.get(slot_name, 0)


class _RecordingCtx:
    def __init__(self, manager: _RecordingSlotManager, slot_name: str) -> None:
        self._manager = manager
        self._slot_name = slot_name

    async def __aenter__(self) -> None:
        self._manager.events.append(("enter", self._slot_name))
        self._manager._counts[self._slot_name] = (
            self._manager._counts.get(self._slot_name, 0) + 1
        )

    async def __aexit__(self, *_: Any) -> None:
        self._manager.events.append(("exit", self._slot_name))
        self._manager._counts[self._slot_name] = (
            self._manager._counts.get(self._slot_name, 1) - 1
        )


def _make_dispatcher(
    transport: httpx.MockTransport,
    sm: _RecordingSlotManager | None = None,
) -> Dispatcher:
    client = httpx.AsyncClient(transport=transport)
    return Dispatcher(http_client=client, slot_manager=sm)  # type: ignore[arg-type]


def _slot_call(streaming: bool = False) -> UpstreamCall:
    return UpstreamCall(
        upstream_name="primary",
        target_url="http://slot/chat/completions",
        headers={"content-type": "application/json"},
        body=b"{}",
        streaming=streaming,
        method="POST",
        slot_name="primary",
    )


def _remote_call() -> UpstreamCall:
    return UpstreamCall(
        upstream_name="openrouter",
        target_url="http://remote/chat/completions",
        headers={"content-type": "application/json"},
        body=b"{}",
        streaming=False,
        method="POST",
        slot_name="",  # remote — no slot
    )


# ── non-streaming ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forward_enters_and_exits_serving_for_slot_call() -> None:
    sm = _RecordingSlotManager()
    dispatcher = _make_dispatcher(
        httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True})),
        sm=sm,
    )
    try:
        resp = await dispatcher.forward(_slot_call())
        assert resp.status_code == 200
        assert sm.events == [("enter", "primary"), ("exit", "primary")]
        assert sm.in_flight_count("primary") == 0
    finally:
        await dispatcher.aclose()


@pytest.mark.asyncio
async def test_forward_releases_serving_on_network_error() -> None:
    """A connect error must still release the serving counter."""
    sm = _RecordingSlotManager()

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=req)

    dispatcher = _make_dispatcher(httpx.MockTransport(handler), sm=sm)
    try:
        with pytest.raises(UpstreamUnavailable):
            await dispatcher.forward(_slot_call())
        assert sm.in_flight_count("primary") == 0
        # Both enter + exit landed.
        ops = [op for op, _ in sm.events]
        assert ops == ["enter", "exit"]
    finally:
        await dispatcher.aclose()


@pytest.mark.asyncio
async def test_forward_remote_call_does_not_touch_slot_manager() -> None:
    """Remote-kind upstreams leave the slot machinery alone."""
    sm = _RecordingSlotManager()
    dispatcher = _make_dispatcher(
        httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True})),
        sm=sm,
    )
    try:
        resp = await dispatcher.forward(_remote_call())
        assert resp.status_code == 200
        assert sm.events == [], "remote upstream must not enter serving()"
    finally:
        await dispatcher.aclose()


# ── streaming ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forward_streaming_holds_serving_until_drain() -> None:
    """SERVING releases only after the stream is fully consumed."""
    sm = _RecordingSlotManager()
    chunks = [b"data: 1\n\n", b"data: 2\n\n", b"data: [DONE]\n\n"]

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b"".join(chunks)),
            headers={"content-type": "text/event-stream"},
        )

    dispatcher = _make_dispatcher(httpx.MockTransport(handler), sm=sm)
    try:
        resp = await dispatcher.forward(_slot_call(streaming=True))
        # forward() returned but the stream hasn't drained yet — slot
        # must still be marked SERVING.
        assert sm.events == [("enter", "primary")]
        assert sm.in_flight_count("primary") == 1

        collected = b""
        async for c in resp.body_iterator:
            collected += c if isinstance(c, bytes) else c.encode()

        # After draining, exit fires.
        assert collected == b"".join(chunks)
        assert sm.events == [("enter", "primary"), ("exit", "primary")]
        assert sm.in_flight_count("primary") == 0
    finally:
        await dispatcher.aclose()


# ── single-flight prefetch isolation ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_flight_prefetch_does_not_enter_serving() -> None:
    """Cold-cache prefetch via SingleFlightGroup never touches slot state.

    Prefetch only calls ``fetch_models`` (a /v1/models GET).  forward()
    is the only path that enters serving() — and prefetch happens inside
    dispatch(), never forward().  This test verifies the boundary holds
    by exercising _cold_prefetch directly while a SlotManager stand-in
    watches for unexpected enter calls.
    """
    sm = _RecordingSlotManager()

    async def fetcher(_u: Any) -> list[str]:
        return ["model-a", "model-b"]

    dispatcher = Dispatcher(
        fetch_models=fetcher,  # type: ignore[arg-type]
        slot_manager=sm,  # type: ignore[arg-type]
    )
    from hal0.upstreams.registry import Upstream

    cold = [Upstream(name="r", kind="remote", url="http://x")]
    await dispatcher._cold_prefetch(cold)
    await dispatcher.aclose()

    assert sm.events == [], "prefetch must never enter serving()"

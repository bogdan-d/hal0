"""OpenAI-compatible endpoints (mounted under /v1).

All POST endpoints share the same shape: parse the JSON body, hand it to
:meth:`Dispatcher.dispatch` to resolve an :class:`UpstreamCall`, then
:meth:`Dispatcher.forward` it.  Streaming responses (SSE for chat /
completions, binary for ``/audio/speech``) and non-streaming responses
are both handled inside ``forward`` — this module just exposes the
endpoints.

GET ``/v1/models`` aggregates the model ids advertised by every
configured upstream's ``/v1/models``.  Returns the OpenAI shape so
clients (OpenWebUI, the chat UI, third-party SDKs) work unmodified.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from hal0.api.deps import DispatcherDep

router = APIRouter()


def _instrument_streaming_throughput(
    response: StreamingResponse, app_state: Any
) -> StreamingResponse:
    """Wrap a streaming response body iterator with a token counter.

    Increments ``app_state.tps_events`` with one (monotonic, tokens)
    entry per chunk. Token count per chunk is approximated by counting
    ``"delta":`` occurrences in the raw SSE bytes — close enough for a
    throughput indicator and far cheaper than a full SSE parse.
    """
    original = response.body_iterator
    events = getattr(app_state, "tps_events", None)
    if events is None:
        return response

    async def _counting() -> Any:
        async for chunk in original:
            if isinstance(chunk, (bytes, bytearray)):
                tokens = chunk.count(b'"delta":')
                if tokens > 0:
                    events.append((time.monotonic(), tokens))
            elif isinstance(chunk, str):
                tokens = chunk.count('"delta":')
                if tokens > 0:
                    events.append((time.monotonic(), tokens))
            yield chunk

    response.body_iterator = _counting()
    return response


def _record_nonstreaming_throughput(body_bytes: bytes, app_state: Any) -> None:
    """Pull ``usage.completion_tokens`` + a recent timestamp out of a JSON
    response body so non-streaming chats also move the throughput tile."""
    events = getattr(app_state, "tps_events", None)
    if events is None or not body_bytes:
        return
    try:
        data = json.loads(body_bytes)
    except (ValueError, TypeError):
        return
    if not isinstance(data, dict):
        return
    usage = data.get("usage") or {}
    completion = usage.get("completion_tokens") or 0
    if not isinstance(completion, (int, float)) or completion <= 0:
        return
    # Without a real start time, attribute the whole completion to "now"
    # — the rolling window will smear it across the lookback. Better
    # alternatives need start-time tracking through forward().
    events.append((time.monotonic(), int(completion)))


async def _read_json_body(request: Request) -> dict[str, Any]:
    """Best-effort JSON parse.  Empty / malformed bodies become ``{}``.

    The dispatcher tolerates empty bodies (path-default model resolution
    kicks in); validation of the parsed shape belongs to the upstream.
    """
    try:
        raw = await request.body()
    except Exception:
        return {}
    if not raw:
        return {}
    import json

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _dispatch_and_forward(
    request: Request,
    dispatcher: DispatcherDep,
) -> Response:
    body = await _read_json_body(request)
    call = await dispatcher.dispatch(request, body=body)
    # Remember the most recent model we sent to this upstream so the
    # dashboard's synthetic slot reflects what's actually being used,
    # not the first-non-alias from the catalog.
    last_used = getattr(request.app.state, "last_used_model", None)
    if last_used is not None and call.upstream_name and call.resolved_model:
        last_used[call.upstream_name] = call.resolved_model

    response = await dispatcher.forward(call)
    if isinstance(response, StreamingResponse):
        return _instrument_streaming_throughput(response, request.app.state)
    if isinstance(response, Response) and getattr(response, "body", None):
        _record_nonstreaming_throughput(response.body, request.app.state)
    return response


@router.get("/models")
async def list_models(
    request: Request,
    dispatcher: DispatcherDep,
) -> dict[str, object]:
    """Aggregate ``/v1/models`` across every configured upstream.

    Returns the OpenAI shape: ``{"object": "list", "data": [...]}``.
    Fetches each upstream's catalog on demand (no caching yet — a TTL
    cache lands when the dispatcher gets one).
    """
    upstreams = request.app.state.upstreams
    seen: set[str] = set()
    data: list[dict[str, Any]] = []
    now = int(time.time())
    for u in upstreams.list():
        try:
            advertised = await upstreams.fetch_models(u.name)
        except Exception:
            advertised = []
        for mid in advertised:
            if mid in seen:
                continue
            seen.add(mid)
            data.append(
                {
                    "id": mid,
                    "object": "model",
                    "created": now,
                    "owned_by": u.name,
                }
            )
    return {"object": "list", "data": data}


@router.get("/models/{model_id:path}")
async def get_model(
    model_id: str,
    request: Request,
    dispatcher: DispatcherDep,
) -> dict[str, object]:
    listing = await list_models(request, dispatcher)
    for entry in listing.get("data", []):  # type: ignore[union-attr]
        if isinstance(entry, dict) and entry.get("id") == model_id:
            return entry
    from hal0.dispatcher.router import NoRouteFound

    raise NoRouteFound(
        f"model {model_id!r} is not advertised by any configured upstream",
        details={"model": model_id},
    )


@router.post("/chat/completions")
async def chat_completions(request: Request, dispatcher: DispatcherDep) -> Response:
    return await _dispatch_and_forward(request, dispatcher)


@router.post("/completions")
async def completions(request: Request, dispatcher: DispatcherDep) -> Response:
    return await _dispatch_and_forward(request, dispatcher)


@router.post("/embeddings")
async def embeddings(request: Request, dispatcher: DispatcherDep) -> Response:
    return await _dispatch_and_forward(request, dispatcher)


@router.post("/rerankings")
async def rerankings(request: Request, dispatcher: DispatcherDep) -> Response:
    return await _dispatch_and_forward(request, dispatcher)


@router.post("/audio/transcriptions")
async def audio_transcriptions(request: Request, dispatcher: DispatcherDep) -> Response:
    return await _dispatch_and_forward(request, dispatcher)


@router.post("/audio/speech")
async def audio_speech(request: Request, dispatcher: DispatcherDep) -> Response:
    return await _dispatch_and_forward(request, dispatcher)

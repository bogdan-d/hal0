"""Model registry endpoints (mounted under /api/models).

This is the *internal* models surface for the dashboard — distinct from
OpenAI-compat `/v1/models`.  Aggregates entries from every configured
upstream so the dashboard's Models view shows what's actually reachable,
plus any locally-registered models from the ModelRegistry.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request

from hal0.api.middleware.error_codes import Hal0Error

router = APIRouter()


# Known-alias model ids that upstream gateways advertise as routing
# shortcuts (haloai's hermes-proxy exposes them as "primary", "tiny",
# etc., plus haloai:* namespaced variants).  Filtered from the dashboard
# Models view because they're not real models — they're routes.
_ALIAS_NAMES = frozenset(
    {
        "primary",
        "medium",
        "tiny",
        "embed",
        "rerank",
        "npu",
        "coding",
        "coder",
        "whisper",
        "moonshine",
        "vibevoice",
        "kokoro",
        "tts-1",
        "tts-1-hd",
        "bge-reranker",
        "nomic-embed",
    }
)


def _is_alias(model_id: str) -> bool:
    """Filter out routing aliases that aren't real models."""
    if model_id.startswith("haloai:"):
        return True
    return model_id in _ALIAS_NAMES


class NotImplementedYet(Hal0Error):
    code = "system.not_implemented"
    status = 501


@router.get("")
async def list_models(request: Request) -> dict[str, Any]:
    """Aggregate models from every upstream.  Dashboard reads this."""
    upstreams = request.app.state.upstreams
    cache = getattr(request.app.state, "model_cache", {})
    now = int(time.time())
    data: list[dict[str, Any]] = []
    seen: set[str] = set()
    filtered = 0
    for u in upstreams.list():
        try:
            ids = cache.get(u.name) or await upstreams.fetch_models(u.name)
            cache[u.name] = ids
        except Exception:
            ids = []
        for mid in ids:
            if mid in seen:
                continue
            if _is_alias(mid):
                filtered += 1
                continue
            seen.add(mid)
            data.append(
                {
                    "id": mid,
                    "name": mid,
                    "object": "model",
                    "created": now,
                    "owned_by": u.name,
                    "upstream": u.name,
                }
            )
    return {"models": data, "count": len(data), "filtered_aliases": filtered}


@router.post("", status_code=201)
async def create_model(request: Request) -> dict[str, Any]:
    """Register a new model in the local ModelRegistry.

    Body shape: serialized ``Model`` — see ``hal0.registry.store.Model``.
    The model must already exist on disk (e.g. dropped into
    ``/var/lib/hal0/models/``) — this endpoint records metadata, it does
    not download. Use POST /api/models/{id}/pull for downloads.
    """
    from hal0.registry.store import Model

    registry = request.app.state.model_registry
    try:
        body = await request.json()
    except Exception as exc:
        raise Hal0Error("body must be valid JSON", details={"error": str(exc)}) from exc
    if not isinstance(body, dict):
        raise Hal0Error("body must be a JSON object")
    try:
        model = Model(**body)
    except (TypeError, ValueError) as exc:
        raise Hal0Error(f"invalid Model payload: {exc}") from exc
    registry.add(model)
    return _model_to_dict(model)


def _model_to_dict(model: Any) -> dict[str, Any]:
    """Serialise a registry Model to the dashboard's flat shape."""
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return {**getattr(model, "__dict__", {})}


@router.get("/{model_id:path}")
async def get_model(model_id: str, request: Request) -> dict[str, Any]:
    """Return a single model by id, preferring the local registry then
    falling back to whichever upstream advertises it."""
    registry = request.app.state.model_registry
    if registry.has(model_id):
        return _model_to_dict(registry.get(model_id))
    listing = await list_models(request)
    for m in listing["models"]:
        if m["id"] == model_id:
            return m
    raise Hal0Error(
        f"model {model_id!r} not found in registry or any upstream catalog",
        details={"model_id": model_id},
    )


@router.put("/{model_id:path}")
async def update_model(model_id: str, request: Request) -> dict[str, Any]:
    """Apply partial updates to a registered model's metadata."""
    registry = request.app.state.model_registry
    try:
        body = await request.json()
    except Exception as exc:
        raise Hal0Error("body must be valid JSON", details={"error": str(exc)}) from exc
    if not isinstance(body, dict):
        raise Hal0Error("body must be a JSON object")
    model = registry.update(model_id, body)
    return _model_to_dict(model)


@router.delete("/{model_id:path}")
async def delete_model(model_id: str, request: Request) -> dict[str, object]:
    """Remove a model from the local registry (does not delete files)."""
    registry = request.app.state.model_registry
    removed = registry.remove(model_id)
    return {"id": model_id, "deleted": bool(removed)}


@router.post("/{model_id:path}/pull")
async def pull_model(model_id: str) -> dict[str, object]:
    raise NotImplementedYet(f"pull_model {model_id}: model-download flow lands with the installer")

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


@router.post("")
async def create_model() -> dict[str, object]:
    raise NotImplementedYet("create_model: registry-side model authoring lands with the installer")


@router.get("/{model_id:path}")
async def get_model(model_id: str, request: Request) -> dict[str, Any]:
    listing = await list_models(request)
    for m in listing["models"]:
        if m["id"] == model_id:
            return m
    raise NotImplementedYet(f"get_model {model_id}: not found in any upstream catalog")


@router.put("/{model_id:path}")
async def update_model(model_id: str) -> dict[str, object]:
    raise NotImplementedYet(f"update_model {model_id}: registry-side authoring is post-installer")


@router.delete("/{model_id:path}")
async def delete_model(model_id: str) -> dict[str, object]:
    raise NotImplementedYet(f"delete_model {model_id}: registry-side authoring is post-installer")


@router.post("/{model_id:path}/pull")
async def pull_model(model_id: str) -> dict[str, object]:
    raise NotImplementedYet(f"pull_model {model_id}: model-download flow lands with the installer")

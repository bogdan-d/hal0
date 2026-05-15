"""Image cache HTTP surface.

Serves PNGs that ``POST /v1/images/generations`` wrote into
``/var/lib/hal0/images/cache/`` when the OpenAI body asked for
``response_format: "url"``.

Mounted at ``/api/images/cache/{name}.png`` so the URL is stable across
hal0 versions and self-explanatory to operators reading server logs.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from hal0.api import image_cache
from hal0.errors import Hal0Error

router = APIRouter()


class _ImageCacheNotFound(Hal0Error):
    code = "image.cache_miss"
    status = 404


@router.get("/cache/{name}")
async def get_cached_image(name: str) -> Response:
    """Return one cached PNG by name.

    The name is the bare uuid hex (with or without ``.png`` suffix). The
    cache layer rejects names that don't match its safe-name regex, so
    a path-traversal attempt bounces with the same 404 envelope as a
    plain miss.
    """
    png_bytes = image_cache.read_png(name)
    if png_bytes is None:
        raise _ImageCacheNotFound(
            f"no cached image named {name!r}",
            details={"name": name},
        )
    # Cache headers: the file content is uniquely identified by the uuid
    # in the URL, so we can flag it as immutable for a long time. The LRU
    # eviction may delete it eventually but a downstream cache returning
    # a stale 404 is harmless (clients re-generate).
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


__all__ = ["router"]

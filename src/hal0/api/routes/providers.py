"""External upstream LLM providers (mounted under /api).

Endpoints:
  GET    /api/upstreams
  POST   /api/upstreams
  PUT    /api/upstreams/{name}
  DELETE /api/upstreams/{name}
  POST   /api/upstreams/{name}/test
  GET    /api/providers/catalog
  GET    /api/providers
  POST   /api/providers
  GET    /api/providers/{pid}
  PUT    /api/providers/{pid}
  DELETE /api/providers/{pid}
  POST   /api/providers/{pid}/test
"""

from __future__ import annotations

from fastapi import APIRouter

from hal0.api.middleware.error_codes import Hal0Error

router = APIRouter()


class NotImplementedYet(Hal0Error):
    code = "system.not_implemented"
    status = 501


@router.get("/upstreams")
async def list_upstreams() -> list[dict[str, object]]:
    raise NotImplementedYet("list_upstreams: Phase 1")


@router.get("/providers/catalog")
async def providers_catalog() -> dict[str, object]:
    raise NotImplementedYet("providers_catalog: Phase 1")


@router.get("/providers")
async def list_providers() -> list[dict[str, object]]:
    raise NotImplementedYet("list_providers: Phase 1")

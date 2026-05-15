"""Config + URL discovery endpoints (mounted under /api/config)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/urls")
async def get_urls() -> dict[str, str]:
    # Phase 1: read from config + hardware probe to construct real URLs.
    return {
        "api": "http://127.0.0.1:8080",
        "openwebui": "http://127.0.0.1:3001",
    }

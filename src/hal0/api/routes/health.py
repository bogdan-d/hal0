"""Health, status, metrics, features.

Routes mounted under /api:
  GET  /api/status            — overall liveness + summary
  GET  /api/health/system     — deep health (slots, disk, ram)
  GET  /api/metrics           — JSON metrics
  GET  /api/metrics/prometheus — text/plain prometheus exposition
  GET  /api/features          — feature flags
  PUT  /api/features/{name}   — toggle feature flag
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from hal0 import __version__

router = APIRouter()


class StatusResponse(BaseModel):
    name: str = "hal0"
    version: str
    status: str


@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    return StatusResponse(version=__version__, status="ok")


@router.get("/health/system")
async def health_system() -> dict[str, object]:
    return {"status": "ok", "checks": {}}  # TODO Phase 1: real checks


@router.get("/metrics")
async def metrics() -> dict[str, object]:
    return {"slots": {}, "hardware": {}, "dispatcher": {}}  # TODO Phase 1


@router.get("/features")
async def list_features() -> dict[str, bool]:
    return {}  # TODO Phase 1

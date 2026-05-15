"""FastAPI application factory.

The module-level `app` exists so `uvicorn hal0.api:app` works directly.
For tests and alternate entrypoints, call `create_app()`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from hal0 import __version__
from hal0.api.middleware import error_codes, request_id
from hal0.api.routes import (
    config as config_routes,
)
from hal0.api.routes import (
    hardware,
    health,
    installer,
    logs,
    models,
    providers,
    settings,
    slots,
    updater,
    v1,
)

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("hal0.api.startup", version=__version__)
    yield
    log.info("hal0.api.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="hal0",
        version=__version__,
        description="Open-source home AI inference platform",
        lifespan=lifespan,
        # OpenAPI docs at /api/docs to keep `/docs` reserved for the UI later
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    request_id.install(app)
    error_codes.install(app)

    # OpenAI-compatible endpoints
    app.include_router(v1.router, prefix="/v1", tags=["v1"])

    # Internal API
    app.include_router(slots.router, prefix="/api/slots", tags=["slots"])
    app.include_router(models.router, prefix="/api/models", tags=["models"])
    app.include_router(hardware.router, prefix="/api", tags=["hardware"])
    app.include_router(logs.router, prefix="/api/logs", tags=["logs"])
    app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(providers.router, prefix="/api", tags=["providers"])
    app.include_router(config_routes.router, prefix="/api/config", tags=["config"])
    app.include_router(updater.router, prefix="/api/updates", tags=["updater"])
    app.include_router(installer.router, prefix="/api/install", tags=["installer"])

    return app


app = create_app()

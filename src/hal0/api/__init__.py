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
from hal0.config.loader import ConfigParseError, load_upstreams_config
from hal0.dispatcher.router import Dispatcher
from hal0.hardware.probe import HardwareProbe
from hal0.registry.store import ModelRegistry
from hal0.upstreams.registry import Upstream, UpstreamRegistry

log = structlog.get_logger(__name__)


def _hydrate_upstreams(registry: UpstreamRegistry) -> None:
    """Populate the upstream registry from /etc/hal0/upstreams.toml.

    Missing file is fine — fresh installs have an empty registry until
    the user adds an upstream via the UI or `hal0 upstream add`.  Malformed
    files surface a typed ConfigParseError that propagates to the lifespan;
    we log+continue rather than crashing the API so the UI can still load
    and show the config error to the user.
    """
    try:
        cfg = load_upstreams_config()
    except ConfigParseError as exc:
        log.warning("upstreams.config_parse_failed", error=str(exc))
        return
    for entry in cfg.upstream:
        try:
            registry.upsert(
                Upstream(
                    name=entry.name,
                    kind=entry.kind,
                    url=entry.url,
                    auth_style=entry.auth_style,
                    auth_value_env=entry.auth_value_env,
                    timeout_seconds=entry.timeout_seconds,
                    slot_name=entry.slot_name,
                    warmup_strategy=entry.warmup_strategy,
                    advertise_models=entry.advertise_models,
                )
            )
        except Exception as exc:
            log.warning(
                "upstreams.entry_skipped",
                name=entry.name,
                error=str(exc),
                error_type=type(exc).__name__,
            )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("hal0.api.startup", version=__version__)

    upstreams = UpstreamRegistry()
    _hydrate_upstreams(upstreams)
    model_registry = ModelRegistry()
    hardware_probe = HardwareProbe()

    # Shared in-process /v1/models cache.  The dispatcher's cold-cache
    # prefetch path needs cached_models() and fetch_models() to share
    # state — without this, prefetch fans out then re-checks the cache
    # and finds it empty, and every request 404s.
    # NOTE: no TTL yet; cache persists for the life of the process.
    # A TTL / invalidation strategy lands when the dispatcher gets its
    # own cache layer.
    model_cache: dict[str, list[str]] = {}

    async def _fetch_and_cache(u: Upstream) -> list[str]:
        models = await upstreams.fetch_models(u.name)
        model_cache[u.name] = models
        return models

    dispatcher = Dispatcher(
        upstream_registry=upstreams,
        model_registry=model_registry,
        cached_models=lambda name: model_cache.get(name, []),
        fetch_models=_fetch_and_cache,
    )

    app.state.upstreams = upstreams
    app.state.model_registry = model_registry
    app.state.hardware_probe = hardware_probe
    app.state.dispatcher = dispatcher
    app.state.model_cache = model_cache
    # Tracks the most recent model id sent to each upstream so the
    # dashboard's synthetic slot reflects current usage instead of the
    # first-non-alias from the catalog. Populated by v1 routes after
    # dispatch resolves.
    app.state.last_used_model = {}
    # Rolling window of (monotonic_ts, tokens_in_chunk) tuples for the
    # streaming forward path. Lets /api/slots/metrics surface a real
    # current-throughput number even when the upstream's own metrics
    # endpoint doesn't report tps (FLM/NPU slots in haloai).
    import collections

    app.state.tps_events = collections.deque(maxlen=4096)

    log.info(
        "hal0.api.upstreams_loaded",
        count=len(upstreams.list()),
        names=[u.name for u in upstreams.list()],
    )

    try:
        yield
    finally:
        await dispatcher.aclose()
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

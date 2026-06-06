"""hal0 memory subsystem (ADR-0005 + brain-redesign P0-P2).

Public contract for ``/mcp/memory`` + ``/api/memory/*``. Exposes the
engine-neutral :class:`MemoryProvider` ABC and the ``provider_from_config``
factory that the one construction site in ``api/__init__.py`` calls.
"""

from __future__ import annotations

from typing import Any

import structlog

from hal0.memory.cognee_wrapper import CogneeWrapper, MemoryRecord
from hal0.memory.provider import (
    AddResult,
    DeleteResult,
    GraphStatus,
    ListPage,
    MemoryItem,
    MemoryProvider,
    Mode,
)

log = structlog.get_logger(__name__)

__all__ = [
    "AddResult",
    "CogneeWrapper",
    "DeleteResult",
    "GraphStatus",
    "ListPage",
    "MemoryItem",
    "MemoryProvider",
    "MemoryRecord",
    "Mode",
    "provider_from_config",
]


def provider_from_config(cfg: Any) -> MemoryProvider:
    """Construct the active MemoryProvider from the loaded hal0 config.

    P0: only the ``cognee`` branch is wired (default). P1 adds ``hindsight``
    + the degrade ladder; P2 flips the default. ``cfg`` is the object returned
    by ``hal0.config.loader.load_hal0_config``.
    """
    engine = str(getattr(cfg.memory, "engine", "cognee") or "cognee").lower()
    embed = cfg.memory.embedding
    graph = cfg.memory.graph

    if engine == "cognee":
        return CogneeWrapper(
            embedding_model=str(embed.model),
            graph_enabled=bool(graph.enabled),
            graph_route=str(graph.route),
            rerank_enabled=bool(embed.rerank_enabled),
            rerank_url=str(embed.rerank_url),
            rerank_over_fetch_factor=int(embed.rerank_over_fetch_factor),
            rerank_max_candidates=int(embed.rerank_max_candidates),
            rerank_connect_timeout_s=float(embed.rerank_connect_timeout_s),
            rerank_read_timeout_s=float(embed.rerank_read_timeout_s),
        )

    # P1 wires hindsight/mem0/pgvector here.
    log.warning("hal0.memory.unknown_engine", engine=engine, fallback="cognee")
    return CogneeWrapper(embedding_model=str(embed.model))

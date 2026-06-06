"""provider_from_config factory tests (P0: Cognee-only branch)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from hal0.memory import provider_from_config


def _cfg(engine="cognee"):
    return SimpleNamespace(
        memory=SimpleNamespace(
            engine=engine,
            embedding=SimpleNamespace(
                model="BAAI/bge-small-en-v1.5",
                rerank_enabled=False,
                rerank_url="http://127.0.0.1:8086",
                rerank_over_fetch_factor=5,
                rerank_max_candidates=500,
                rerank_connect_timeout_s=1.0,
                rerank_read_timeout_s=8.0,
            ),
            graph=SimpleNamespace(enabled=False, route="upstream"),
        )
    )


def test_factory_returns_cognee_for_default_engine():
    # Patch the constructor so we don't stand up real Cognee.
    with patch("hal0.memory.CogneeWrapper", autospec=True) as mock_cls:
        provider_from_config(_cfg("cognee"))
        assert mock_cls.called

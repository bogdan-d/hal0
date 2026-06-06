"""[memory] engine selector field (brain-redesign P1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hal0.config.schema import MemoryConfig


def test_engine_defaults_to_cognee():
    assert MemoryConfig().engine == "cognee"


def test_engine_accepts_known_engines():
    for e in ("cognee", "hindsight", "mem0", "pgvector"):
        assert MemoryConfig(engine=e).engine == e


def test_engine_rejects_unknown():
    with pytest.raises(ValidationError):
        MemoryConfig(engine="weaviate")

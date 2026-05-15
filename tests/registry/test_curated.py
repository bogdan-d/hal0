"""Tests for the curated model catalogue."""

from __future__ import annotations

import pytest

from hal0.registry.curated import (
    CURATED_BY_ID,
    CURATED_MODELS,
    CuratedModel,
    get_curated,
)


def test_catalogue_has_named_picks() -> None:
    """The wizard contract names these three — they must always be present."""
    ids = {m.id for m in CURATED_MODELS}
    assert {"qwen3-4b", "llama32-3b", "phi3-mini"}.issubset(ids)


def test_catalogue_entries_have_hf_coordinates() -> None:
    """Every entry must carry hf_repo + hf_file (the pull layer's input)."""
    for m in CURATED_MODELS:
        assert m.hf_repo, f"{m.id}: hf_repo is required"
        assert m.hf_file, f"{m.id}: hf_file is required"
        assert m.hf_file.endswith(".gguf"), f"{m.id}: not a GGUF file"


def test_get_curated_hit_and_miss() -> None:
    assert get_curated("qwen3-4b") is not None
    assert get_curated("not-a-real-id") is None


def test_curated_model_validates_required_fields() -> None:
    """The Pydantic model rejects missing required fields."""
    with pytest.raises(Exception):
        CuratedModel(id="test")  # type: ignore[call-arg]


def test_lookup_index_matches_list() -> None:
    """CURATED_BY_ID is the same set as the list."""
    assert set(CURATED_BY_ID.keys()) == {m.id for m in CURATED_MODELS}

"""Tests for the custom-GGUF curated coords added in fix/stack-model-pull-coords.

These ids are referenced by exported stacks but were originally auto-scanned
into the registry with EMPTY hf_repo/hf_file. Registering their HF coordinates
in the curated catalogue makes pull-by-id (via ``get_curated`` fallback in
``_resolve_pull_source``), scan-backfill, and stack export all resolve.
"""

from __future__ import annotations

import pytest

from hal0.registry.curated import get_curated
from hal0.registry.discover import _match_curated

# (registry id, hf_repo, hf_file) for each of the 10 added entries.
_EXPECTED: list[tuple[str, str, str]] = [
    (
        "qwen3-6-35b-a3b-nsc-ace-saber-mtp-f16-to-rocmfp4-strix-lean",
        "jcbtc/chadrock-35b-ace-saber-rocmfp4-mtp",
        "Qwen3.6-35B-A3B-NSC-ACE-SABER-MTP-F16-to-ROCmFP4-STRIX_LEAN.gguf",
    ),
    (
        "chadrock3-6-27b-pi-agent-mtp-rocmfp4-strix-lean",
        "jcbtc/chadrock3.6-27b-pi-agent-rocmfp4-mtp",
        "CHADROCK3.6-27B-Pi-Agent-MTP-ROCmFP4-STRIX_LEAN.gguf",
    ),
    (
        "chadrock3-6-35b-uncensored-mtp-strix-lean",
        "jcbtc/CHADROCK3.6-35B-UNCENSORED-MTP-STRIX-LEAN",
        "CHADROCK3.6-35B-UNCENSORED-MTP-STRIX-LEAN.gguf",
    ),
    (
        "qwen3-6-35b-a3b-halostrix-dyn-mtp-v7",
        "jcbtc/qwen3.6-35b-a3b-crown-halo-mtp-dynamic",
        "Qwen3.6-35B-A3B-HaloStrix-Dyn-MTP-v7.gguf",
    ),
    (
        "qwopus3-6-27b-v2-mtp-bf16-to-rocmfp4-strix-lean",
        "jcbtc/qwopus3.6-27b-v2-chadrock-rocmfp4-mtp",
        "Qwopus3.6-27B-v2-MTP-BF16-to-ROCmFP4-STRIX_LEAN.gguf",
    ),
    (
        "qwopus3-6-27b-coder-mtp-q6-k",
        "Jackrong/Qwopus3.6-27B-Coder-MTP-GGUF",
        "Qwopus3.6-27B-Coder-MTP-Q6_K.gguf",
    ),
    (
        "qwopus3-5-9b-coder-mtp-q6-k",
        "Jackrong/Qwopus3.5-9B-Coder-MTP-GGUF",
        "Qwopus3.5-9B-Coder-MTP-Q6_K.gguf",
    ),
    (
        "qwopus3-5-4b-coder-mtp-q6-k",
        "Jackrong/Qwopus3.5-4B-Coder-MTP-GGUF",
        "Qwopus3.5-4B-Coder-MTP-Q6_K.gguf",
    ),
    (
        "qwen3-5-9b-deepseek-v4-flash-mtp-q6-k",
        "Jackrong/Qwen3.5-9B-DeepSeek-V4-Flash-MTP-GGUF",
        "Qwen3.5-9B-DeepSeek-V4-Flash-MTP-Q6_K.gguf",
    ),
    (
        "gemma-4-12b-it-ud-q4-k-xl",
        "unsloth/gemma-4-12b-it-GGUF",
        "gemma-4-12b-it-UD-Q4_K_XL.gguf",
    ),
]


@pytest.mark.parametrize(("model_id", "hf_repo", "hf_file"), _EXPECTED)
def test_get_curated_resolves_exact_coords(model_id: str, hf_repo: str, hf_file: str) -> None:
    """Each new id resolves via get_curated() to the EXACT hf_repo/hf_file.

    This is what makes pull-by-id work for a coord-less registry row:
    ``_resolve_pull_source`` falls back to ``get_curated(model_id)``.
    """
    entry = get_curated(model_id)
    assert entry is not None, f"{model_id} not in curated catalogue"
    assert entry.hf_repo == hf_repo
    assert entry.hf_file == hf_file
    assert entry.capability == "chat"
    assert entry.backend == "llamacpp"


@pytest.mark.parametrize(("model_id", "hf_repo", "hf_file"), _EXPECTED)
def test_match_curated_by_filename(model_id: str, hf_repo: str, hf_file: str) -> None:
    """The on-disk filename resolves back to the curated entry (scan-backfill)."""
    entry = _match_curated(hf_file)
    assert entry is not None, f"no curated match for {hf_file}"
    assert entry.id == model_id


def test_match_curated_seed_stack_files() -> None:
    """The three seed-stack files match their curated entries by filename."""
    saber = _match_curated("Qwen3.6-35B-A3B-NSC-ACE-SABER-MTP-F16-to-ROCmFP4-STRIX_LEAN.gguf")
    assert saber is not None
    assert saber.id == "qwen3-6-35b-a3b-nsc-ace-saber-mtp-f16-to-rocmfp4-strix-lean"

    pi_agent = _match_curated("CHADROCK3.6-27B-Pi-Agent-MTP-ROCmFP4-STRIX_LEAN.gguf")
    assert pi_agent is not None
    assert pi_agent.id == "chadrock3-6-27b-pi-agent-mtp-rocmfp4-strix-lean"

    coder = _match_curated("Qwopus3.6-27B-Coder-MTP-Q6_K.gguf")
    assert coder is not None
    assert coder.id == "qwopus3-6-27b-coder-mtp-q6-k"


def test_no_duplicate_ids() -> None:
    """The new ids do not collide with any existing curated id."""
    from hal0.registry.curated import CURATED_BY_ID, CURATED_MODELS

    assert len(CURATED_BY_ID) == len(CURATED_MODELS), "duplicate curated id detected"
    for model_id, _, _ in _EXPECTED:
        assert model_id in CURATED_BY_ID

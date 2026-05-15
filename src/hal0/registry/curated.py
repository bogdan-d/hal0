"""Curated model catalogue — the FirstRun wizard's pick list.

The catalogue is a small, hand-picked list of "good defaults" so a fresh
hal0 install can be productive after one click. Each entry points at a
specific GGUF file inside a HuggingFace repo (Q4_K_M usually, picked for
the size/quality sweet spot on Strix Halo's 100 GB unified pool).

The wizard fetches this list via ``GET /api/install/curated-models`` and
renders each as a card. A user who wants something off-catalogue uses
the "custom HF URL" affordance — that goes through the same pull endpoint
without touching the curated list.

# NOTE: the catalogue lives in code (not a TOML file on disk) on purpose:
# it ships *with* a hal0 release so users can't end up on an outdated
# pick list. v0.2 may introduce a remote-fetched manifest with signed
# releases; for v1 a frozen-at-build-time list is plenty.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Schema ─────────────────────────────────────────────────────────────────


class CuratedModel(BaseModel):
    """One curated entry surfaced by the FirstRun wizard.

    The wizard renders these as cards with name + size + VRAM badge +
    license badge. The ``hf_repo`` / ``hf_file`` pair is what gets piped
    into ``POST /api/models/{id}/pull`` to actually download the bytes.
    """

    model_config = {"populate_by_name": True, "str_strip_whitespace": True}

    id: str = Field(..., description="Stable id used as the registry key, e.g. 'qwen3-4b'.")
    display_name: str = Field(..., description="Human-readable name for the card.")
    description: str = Field(..., description="One-line value prop.")
    family: str = Field(..., description="Model family — 'qwen', 'llama', 'phi', etc.")
    size_gb: float = Field(..., description="Approximate on-disk size of the GGUF, in GB.")
    vram_gb_min: float = Field(
        ...,
        description="Minimum recommended VRAM (or unified pool) in GB.",
    )
    license: str = Field(..., description="SPDX-ish license short name, e.g. 'Apache-2.0'.")
    license_url: str = Field(..., description="HTTPS URL to the canonical license text.")
    hf_repo: str = Field(..., description="HuggingFace repo id, e.g. 'Qwen/Qwen3-4B-Instruct-GGUF'.")
    hf_file: str = Field(..., description="Filename within the repo (the GGUF to fetch).")
    context_length: int = Field(..., description="Native context window in tokens.")
    recommended_slot: str = Field(
        default="primary",
        description="Default slot to assign the model to. 'primary' for chat.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Freeform tags shown as chips ('chat', 'vision', 'fast', etc.).",
    )
    notes: str = Field(
        default="",
        description="Operator-facing rationale for the quant pick or anything else worth surfacing.",
    )


# ── The catalogue ──────────────────────────────────────────────────────────
# Picking Q4_K_M as the default quant: best size/quality trade-off in the
# common 2-5 GB range, ships in every reputable GGUF repo. If a repo only
# ships Q4_0 or Q4 (no _K_M), we fall back to the closest equivalent and
# call it out in ``notes``.

CURATED_MODELS: list[CuratedModel] = [
    CuratedModel(
        id="qwen3-4b",
        display_name="Qwen3 4B Instruct",
        description="Multilingual, fast all-rounder. Great default for a 4-8 GB VRAM budget.",
        family="qwen",
        size_gb=2.5,
        vram_gb_min=4.0,
        license="Apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        hf_repo="Qwen/Qwen3-4B-Instruct-GGUF",
        hf_file="qwen3-4b-instruct-q4_k_m.gguf",
        context_length=32768,
        recommended_slot="primary",
        tags=["chat", "multilingual", "balanced"],
        notes="Q4_K_M quant for the size/quality sweet spot.",
    ),
    CuratedModel(
        id="llama32-3b",
        display_name="Llama 3.2 3B Instruct",
        description="Small and fast. Good fit for low-VRAM hosts or quick experimentation.",
        family="llama",
        size_gb=2.0,
        vram_gb_min=3.0,
        license="Llama-3.2-Community",
        license_url="https://www.llama.com/llama3_2/license/",
        hf_repo="bartowski/Llama-3.2-3B-Instruct-GGUF",
        hf_file="Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        context_length=131072,
        recommended_slot="primary",
        tags=["chat", "fast", "low-vram"],
        notes="Q4_K_M from bartowski's GGUF repack (the upstream Meta release ships safetensors only).",
    ),
    CuratedModel(
        id="phi3-mini",
        display_name="Phi-3 Mini 4K Instruct",
        description="Compact reasoning model from Microsoft. MIT licensed.",
        family="phi",
        size_gb=2.4,
        vram_gb_min=3.0,
        license="MIT",
        license_url="https://opensource.org/license/mit",
        hf_repo="microsoft/Phi-3-mini-4k-instruct-gguf",
        hf_file="Phi-3-mini-4k-instruct-q4.gguf",
        context_length=4096,
        recommended_slot="primary",
        tags=["chat", "reasoning", "mit"],
        notes=(
            "Microsoft's official GGUF release ships 'q4' (no _K_M variant); "
            "we use that. Smallest validated catalogue entry — good 'just download something' pick."
        ),
    ),
]


CURATED_BY_ID: dict[str, CuratedModel] = {m.id: m for m in CURATED_MODELS}


def get_curated(model_id: str) -> CuratedModel | None:
    """Return the curated entry by id, or ``None`` if not in the catalogue."""
    return CURATED_BY_ID.get(model_id)


__all__ = [
    "CURATED_BY_ID",
    "CURATED_MODELS",
    "CuratedModel",
    "get_curated",
]

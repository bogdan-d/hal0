"""Model — registry entry pydantic model.

The Model class is the typed representation of one row in the model
registry (stored as atomic TOML under /var/lib/hal0/registry/).

Port target: haloai lib/registry.py (adapted from the raw dict shape
to a pydantic v2 model).  See PLAN.md §3.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

# Capabilities that a model can advertise.
# Used by the Dispatcher and the slot config form's hardware-aware filtering.
# NOTE: revisit in Phase 1 — extend as providers surface new capabilities.
Capability = str  # e.g. "chat", "embed", "rerank", "vision", "asr", "tts"


class Model(BaseModel):
    """A model entry in the hal0 registry.

    All fields are optional at construction (to allow partial updates via
    ModelRegistry.update()), except for `id` and `path` which are always
    required.

    Schema is intentionally flat: the registry TOML uses one file per model
    keyed by model id.  Nested structures are avoided so human editing remains
    practical.
    """

    model_config = {"populate_by_name": True, "str_strip_whitespace": True}

    id: str = Field(..., description="Unique model identifier, e.g. 'qwen3-4b-q4_k_m'.")

    name: str = Field(
        default="",
        description="Human-readable display name, e.g. 'Qwen3 4B (Q4_K_M)'.",
    )

    path: str = Field(
        ...,
        description=(
            "Absolute path to the model file or directory on this host.  "
            "May be under /var/lib/hal0/models/ or a symlink to /mnt/ai-models/."
        ),
    )

    size_bytes: int = Field(
        default=0,
        description="Total size of model files in bytes.  0 means unknown.",
    )

    license: str = Field(
        default="unknown",
        description="SPDX license identifier or short name, e.g. 'Apache-2.0', 'Llama-3'.",
    )

    capabilities: list[Capability] = Field(
        default_factory=list,
        description=(
            "List of capability strings this model supports.  "
            "Valid values: 'chat', 'embed', 'rerank', 'vision', 'asr', 'tts'."
        ),
    )

    hf_repo: str = Field(
        default="",
        description="HuggingFace repo id, e.g. 'Qwen/Qwen3-4B-GGUF'. Empty if not from HF.",
    )

    hf_filename: str = Field(
        default="",
        description="Filename within the HF repo, e.g. 'qwen3-4b-q4_k_m.gguf'.",
    )

    tags: list[str] = Field(
        default_factory=list,
        description="Freeform tags, e.g. ['curated', 'vision'].",
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific or user-defined extra metadata.",
    )

    @field_validator("id")
    @classmethod
    def id_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("model id must not be empty")
        return v

    @field_validator("path")
    @classmethod
    def path_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("model path must not be empty")
        return v

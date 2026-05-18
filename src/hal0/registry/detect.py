"""Model detection — derive backends + capabilities from a file on disk.

Pure inspection: no registry mutation, no network. The output is a
:class:`DetectionResult` that callers (the scan endpoint, the single-file
register path) merge into a :class:`hal0.registry.model.Model` before
persisting.

Detection strategy, cheapest first:

1. ``.gguf`` files → :func:`hal0.registry.gguf_header.read_gguf_header`
   to pull arch + context_length + pooling_type. Strong evidence →
   ``confidence='high'``. The four GGUF backends are seeded:
   ``vulkan``, ``rocm``, ``cuda``, ``cpu``. Capability is ``embed`` when
   ``pooling_type`` is present and non-zero (llama.cpp marks pooling_type
   = NONE as 0 for chat models, > 0 for embed/rerank pooled outputs),
   else ``chat``.
2. Non-GGUF: filename heuristic only.  Keywords cover the providers we
   currently ship:

   * ``embed``, ``bge``, ``e5``, ``nomic`` → ``capabilities=['embed']``
   * ``whisper``, ``moonshine`` → ``capabilities=['asr']`` (backend
     ``moonshine`` only if name contains ``moonshine``)
   * ``kokoro`` → ``capabilities=['tts']``, backend ``kokoro``
   * fallback for ``.gguf`` w/ unreadable header → ``capabilities=['chat']``

   Filename-only detection always returns ``confidence='low'``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from hal0.registry.gguf_header import read_gguf_header

log = logging.getLogger(__name__)

Confidence = Literal["high", "medium", "low"]

# Backends llama-server can target for any GGUF file. The slot config
# picks one based on hardware probe; detection just lists what's *compatible*.
_GGUF_BACKENDS: list[str] = ["vulkan", "rocm", "cuda", "cpu"]

_EMBED_TOKENS = ("embed", "bge", "e5", "nomic", "gte-", "jina-embed")
_ASR_TOKENS = ("whisper", "moonshine", "-asr", "_asr")
_TTS_TOKENS = ("kokoro", "vibevoice", "-tts", "_tts")


def _hf_repo_name_from_path(path: Path) -> str | None:
    """Walk up the path looking for ``models--ORG--REPO`` (HF cache layout).

    Returns ``ORG/REPO`` when found, else ``None``. Useful when scanning the
    HF blob cache directly: blob files are content-hash named so the parent
    ``models--ORG--REPO`` dir is the only meaningful label.
    """
    for parent in path.parents:
        seg = parent.name
        if seg.startswith("models--") and "--" in seg[len("models--") :]:
            rest = seg[len("models--") :]
            parts = rest.split("--", 1)
            if len(parts) == 2:
                return f"{parts[0]}/{parts[1]}"
            return rest
    return None


@dataclass
class DetectionResult:
    """Outcome of a single-file detection pass.

    ``raw_hints`` carries provider-specific bits (the parsed GGUF KV pairs,
    or the matched filename tokens) so downstream UIs can show "why".
    """

    suggested_backends: list[str]
    suggested_capabilities: list[str]
    context_length: int | None = None
    confidence: Confidence = "low"
    suggested_name: str | None = None
    raw_hints: dict[str, Any] = field(default_factory=dict)


# ── helpers ────────────────────────────────────────────────────────────────


def _filename_capability(name: str) -> str | None:
    """Best-effort capability inferred from filename tokens. ``None`` if no hit."""
    lower = name.lower()
    if any(tok in lower for tok in _EMBED_TOKENS):
        return "embed"
    if any(tok in lower for tok in _ASR_TOKENS):
        return "asr"
    if any(tok in lower for tok in _TTS_TOKENS):
        return "tts"
    return None


def _heuristic_only(path: Path) -> DetectionResult:
    """Fallback detection: filename heuristic, no header read."""
    name = path.name.lower()
    cap = _filename_capability(name)

    backends: list[str] = []
    caps: list[str]
    if "moonshine" in name:
        backends = ["moonshine"]
        caps = ["asr"]
    elif "kokoro" in name:
        backends = ["kokoro"]
        caps = ["tts"]
    elif cap is not None:
        caps = [cap]
    else:
        # No idea — default to chat-on-llama-server only if the extension
        # looks like a llama-server-loadable file; otherwise leave empty.
        if path.suffix.lower() in (".gguf",):
            backends = list(_GGUF_BACKENDS)
            caps = ["chat"]
        else:
            caps = []

    return DetectionResult(
        suggested_backends=backends,
        suggested_capabilities=caps,
        context_length=None,
        confidence="low",
        suggested_name=_hf_repo_name_from_path(path),
        raw_hints={"source": "filename", "stem": path.stem, "suffix": path.suffix.lower()},
    )


# ── public API ─────────────────────────────────────────────────────────────


def detect(path: str | Path) -> DetectionResult:
    """Inspect ``path`` and return a :class:`DetectionResult`.

    Never raises for an unreadable / missing / non-GGUF file: we fall
    back to the filename heuristic and lower the confidence.
    """
    p = Path(path)
    suffix = p.suffix.lower()

    # Try GGUF magic bytes regardless of extension — HF blob cache stores
    # GGUF data under content-hash filenames with no suffix.
    header = read_gguf_header(p)
    if header is not None or suffix == ".gguf":
        if header is None:
            # Suffix claimed .gguf but magic failed: degrade to heuristic
            # with the GGUF backend seed.
            r = _heuristic_only(p)
            r.raw_hints["gguf_header_read"] = "failed"
            return r

        arch = header.get("general.architecture")
        ctx_len = header.get("context_length")
        ctx_len_int: int | None = ctx_len if isinstance(ctx_len, int) else None

        pooling = header.get("pooling_type")
        # llama.cpp uses pooling_type=0 (NONE) for causal chat models and
        # >0 (MEAN=1, CLS=2, LAST=3, RANK=4) for embedding / rerank.
        # Treat any positive int as a strong embed signal.
        is_embed = isinstance(pooling, int) and pooling > 0

        # Filename embed-token fallback in case pooling_type is missing
        # but the file is clearly an embed model (some converters drop it).
        if not is_embed and _filename_capability(p.name) == "embed":
            is_embed = True

        caps = ["embed"] if is_embed else ["chat"]

        name_candidate = header.get("general.name") or header.get("general.basename")
        suggested_name = str(name_candidate).strip() if isinstance(name_candidate, str) and name_candidate.strip() else None
        if not suggested_name:
            suggested_name = _hf_repo_name_from_path(p)

        return DetectionResult(
            suggested_backends=list(_GGUF_BACKENDS),
            suggested_capabilities=caps,
            context_length=ctx_len_int,
            confidence="high",
            suggested_name=suggested_name,
            raw_hints={
                "source": "gguf_header",
                "architecture": arch,
                "pooling_type": pooling,
                "version": header.get("version"),
                "name": header.get("general.name"),
                "basename": header.get("general.basename"),
                "size_label": header.get("general.size_label"),
            },
        )

    # Non-GGUF file: filename heuristic only.
    return _heuristic_only(p)


__all__ = [
    "DetectionResult",
    "detect",
]

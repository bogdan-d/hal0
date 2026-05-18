#!/usr/bin/env python3
"""Refresh ``src/hal0/registry/seeds/haloai_models.json`` from haloai.

Fetches ``GET {haloai}/v1/models`` and curates the response into the
shape hal0's registry expects: drops slot route names, prunes obvious
fragment/alias ids, and writes the result as a sorted JSON snapshot.

Run periodically (or before a release) to refresh the seed::

    python scripts/import_haloai_models.py \\
        --haloai http://10.0.1.220:8080 \\
        --output src/hal0/registry/seeds/haloai_models.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

# Real haloai-unknown ids worth keeping (canonical full model names).
KEEP_UNKNOWN = {
    "qwen3-coder-next",
    "qwen3-coder-30b-1m",
    "kappa-20b",
    "deepseek-r1-distill-qwen-32b",
    "llama4-scout",
    "nomic-embed",
    "bge-reranker",
    "qwen3_6-35b-open",
    "qwen3_6-35b",
    "gemma-4-26b",
    "devstral-small-2-24b",
    "qwen3_5-122b-a10b",
    "qwen3-zro-cdr-reason-v2-0.8b-neo-ex-q8",
    # qwen3-zro-cdr-reason-v2-0.8b-neo3-ex-f16 dropped at user's request
    # (2026-05-17); leave the explicit gap so a future seed refresh doesn't
    # silently re-add it.
    "qwen3_5-18b-reap-a3b",
    "qwen3-6-27b",
    "qwen3-6-27b-vision",
    "qwen3-6-27b-heretic-neo-code",
    "reap-coder-40b",
    "reap-coder-48b",
    "reap-coder-25b",
    "hermes-4-14b",
}


def _norm(s: str) -> str:
    return s.lower().removeprefix("haloai:")


def _infer_capability(model: dict[str, Any]) -> str:
    ob = (model.get("owned_by") or "").lower()
    mid = (model.get("id") or "").lower()
    if ob in ("kokoro", "vibevoice"):
        return "tts"
    if ob == "moonshine":
        return "asr"
    if "rerank" in mid:
        return "rerank"
    if "embed" in mid or "nomic" in mid:
        return "embed"
    if "vision" in mid or re.search(r"\bvl\b", mid) or "qwen3vl" in mid or "qwen2.5vl" in mid:
        return "vision"
    if "voice" in mid or "tts" in mid:
        return "tts"
    if "whisper" in mid or "moonshine" in mid or "stt" in mid or "asr" in mid:
        return "asr"
    return "chat"


def _infer_backend(model: dict[str, Any]) -> str:
    ob = (model.get("owned_by") or "").lower()
    if ob == "fastflowlm":
        return "flm"
    if ob in ("llamacpp", "kokoro", "moonshine", "vibevoice", "minimax"):
        return ob
    # haloai-unknown / cold: GGUF-ish ids run on llamacpp.
    return "llamacpp"


def _curate(raw: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (kept_entries, dropped_ids)."""
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    seen: set[str] = set()

    for m in raw:
        mid = m.get("id", "")
        ob = m.get("owned_by", "")
        # Slot route names — not models.
        if ob == "haloai-slot":
            dropped.append(mid)
            continue
        n = _norm(mid)
        # haloai-unknown: judgement-call allowlist.
        if ob == "haloai-unknown" and n not in KEEP_UNKNOWN:
            dropped.append(mid)
            continue
        if n in seen:
            dropped.append(f"DUP:{mid}")
            continue
        seen.add(n)
        meta = m.get("meta") or {}
        kept.append(
            {
                "id": mid,
                "owned_by": ob,
                "upstream": m.get("_upstream") or "",
                "capability": _infer_capability(m),
                "backend": _infer_backend(m),
                "size_bytes": meta.get("size_bytes") or meta.get("size"),
                "params": meta.get("params") or meta.get("parameters"),
                "context_size": (
                    meta.get("context_size") or meta.get("ctx") or meta.get("n_ctx")
                ),
            }
        )
    return kept, dropped


def _fetch(url: str) -> list[dict[str, Any]]:
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
        payload = json.load(resp)
    if isinstance(payload, dict) and "data" in payload:
        return list(payload["data"])
    if isinstance(payload, list):
        return payload
    raise SystemExit(f"unexpected /v1/models payload shape: {type(payload).__name__}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--haloai", default="http://10.0.1.220:8080", help="haloai base URL")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "src"
        / "hal0"
        / "registry"
        / "seeds"
        / "haloai_models.json",
        help="Where to write the curated JSON snapshot.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print summary, don't write.")
    args = parser.parse_args(argv)

    raw = _fetch(f"{args.haloai.rstrip('/')}/v1/models")
    kept, dropped = _curate(raw)

    print(f"fetched {len(raw)} models from {args.haloai}", file=sys.stderr)
    print(f"  kept    : {len(kept)}", file=sys.stderr)
    print(f"  dropped : {len(dropped)}", file=sys.stderr)

    if args.dry_run:
        for d in dropped:
            print(f"  drop: {d}", file=sys.stderr)
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(kept, indent=2) + "\n")
    print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

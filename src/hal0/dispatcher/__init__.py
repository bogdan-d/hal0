"""hal0.dispatcher — Registry-aware request routing.

The Dispatcher reads the model registry and upstream list to decide where
to forward each OpenAI-compatible API request.  It handles:
  - Registry-exact routing (model_id → slot binding)
  - Cold-cache prefetch with single-flight coalescing
  - Remote upstream fallback (OpenRouter, Anthropic, etc.)
  - Structured decision logging to journald

The legacy proxy shim (proxy.py) is kept during Phase 1 and will be
absorbed post-v0.2.

Port targets: haloai lib/dispatcher.py (617 lines), lib/proxy.py.
See PLAN.md §3 and §5 Tier 2/3.

Key exports:
    Dispatcher   — primary entry point; inject via FastAPI Depends().
    UpstreamCall — resolved routing decision returned by Dispatcher.dispatch().
"""

from __future__ import annotations

from hal0.dispatcher.router import Dispatcher, UpstreamCall

__all__ = [
    "Dispatcher",
    "UpstreamCall",
]

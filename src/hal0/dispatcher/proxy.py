"""Legacy proxy fallback for the dispatcher.

Path + model-name heuristics that route a request to a slot when the
registry has nothing to say.  Ported from haloai ``lib/proxy.py`` and kept
during v1.0 as the last-resort step in :class:`Dispatcher.dispatch`.

PLAN.md §3 marks this for absorption into ``router.py`` post-v0.2.  Do not
delete it until then — the v1 dispatcher resolution order explicitly ends
in "legacy fallback" and operator muscle memory ("slot named coding-1m"
addressing) depends on these heuristics.

Port target: haloai ``lib/proxy.py`` (``resolve_slot`` only — the streaming
forwarder lives in :mod:`hal0.dispatcher.router`).
"""

from __future__ import annotations

from typing import Any

from hal0.api.middleware.error_codes import Hal0Error
from hal0.upstreams.registry import Upstream, UpstreamRegistry

# NOTE: revisit in Phase 5 — absorb into router.py after Dispatcher is stable.

# Path fragments that pin a request to a specific slot regardless of model.
# Mirrors haloai lib/proxy.py:51-58 (embeddings + rerank both target embed).
_EMBED_PATHS = ("/embeddings", "/rerank")

# Substrings in the model name that pin to known slot roles.  Order matters:
# the ":" (FLM tag-style id) check runs before the bare-name substring checks
# so that "qwen3.5:embed" still routes to the NPU rather than to embed.
_EMBED_NAME_HINTS = ("embed", "rerank")


class LegacyResolutionFailed(Hal0Error):
    """Raised when the legacy path/name heuristics find no slot to serve a request.

    Carries a ``dispatch.legacy_unresolved`` code so the structured error
    envelope distinguishes "nothing in registry AND nothing in legacy
    fallback" from "registry binding pointed at an unknown upstream."
    """

    code = "dispatch.legacy_unresolved"
    status = 404


def resolve_slot(  # TIER1
    path: str,
    body: dict[str, Any] | None,
    upstreams: UpstreamRegistry,
) -> Upstream:
    """Resolve a request to a slot Upstream using path+name heuristics.

    Mirrors haloai ``lib/proxy.py:resolve_slot`` but returns a typed
    :class:`Upstream` (or raises a typed error) instead of the old
    ``(slot_name, port)`` tuple.

    Resolution rules (in order):
      1. ``/embeddings`` or ``/rerank`` in path → ``embed`` slot.
      2. Model id contains ``:`` (FLM tag-style) → ``npu`` slot.
      3. Model id contains ``embed`` or ``rerank`` substring → ``embed`` slot.
      4. Model id exactly matches a registered slot upstream name (other
         than ``primary``) → that slot.
      5. Fallback → ``primary`` slot.

    Args:
        path:       The original request path (e.g. "/v1/chat/completions").
        body:       Parsed JSON body dict (may be None for GETs).
        upstreams:  Registry to resolve slot names against.

    Returns:
        An :class:`Upstream` representing the slot to forward to.

    Raises:
        LegacyResolutionFailed: If the heuristics select a slot name but no
            matching slot Upstream is registered.  Carries a
            ``dispatch.legacy_unresolved`` code via the typed Hal0Error envelope.
    """
    candidate: str | None = None

    # Rule 1 — path-based pin.
    if any(frag in path for frag in _EMBED_PATHS):
        candidate = "embed"
    elif body:
        model = body.get("model", "")
        if isinstance(model, str) and model:
            m = model.lower()
            # Rule 2 — FLM tag format "name:tag" routes to NPU.
            if ":" in model:
                candidate = "npu"
            # Rule 3 — name-substring pin.
            elif any(hint in m for hint in _EMBED_NAME_HINTS):
                candidate = "embed"
            else:
                # Rule 4 — explicit slot-name addressing.
                slot_match = upstreams.get(m)
                if slot_match is not None and slot_match.kind == "slot" and m != "primary":
                    candidate = m

    # Rule 5 — fallback default slot.
    if candidate is None:
        candidate = "primary"

    upstream = upstreams.get(candidate)
    if upstream is None or upstream.kind != "slot":
        raise LegacyResolutionFailed(
            f"legacy fallback selected slot {candidate!r} but no matching slot upstream is registered",
            details={"slot": candidate, "path": path},
        )
    return upstream


__all__ = ["LegacyResolutionFailed", "resolve_slot"]

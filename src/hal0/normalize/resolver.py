"""Live-slot model resolution for hal0 virtual model names.

Pure core (``resolve_chain``) + an async wrapper (``LiveSlotResolver``) that reads
slot config and the container slot state. The loaded-model set derives from the
slot states SlotManager already tracks — no extra polling.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# ADR-0023: `agent` is the canonical default/anchor role (replaces `chat`); every
# fallback chain ends in `agent`. `utility` is the explicitly-targeted cheap helper
# and is NEVER the fallback for general chat.
_ANCHOR_ROLE = "agent"
_VIRTUAL_PREFIX = "hal0/"

# Canonical virtual names -> ordered chain of roles to try against loaded slots.
# These three are the *advertised* names (the Hermes / OpenWebUI picker). ANY other
# enabled llm slot `X` is still addressable as `hal0/X` via the generalized chain
# built in `_chain_for` — the mapping is read from the live slot set, not frozen here.
DEFAULT_CHAINS: dict[str, tuple[str, ...]] = {
    "hal0/agent": (_ANCHOR_ROLE,),
    # hal0/utility → the cheap helper slot; falls back to the anchor when unloaded.
    "hal0/utility": ("utility", _ANCHOR_ROLE),
    "hal0/npu": ("npu", "utility", _ANCHOR_ROLE),
}


def _chain_for(virtual_name: str, slots: list[SlotView]) -> tuple[str, ...] | None:
    """Resolve a virtual name to an ordered role chain.

    Canonical names (DEFAULT_CHAINS) win. Otherwise ADR-0023 §2 generalization:
    ``hal0/<slot>`` for ANY enabled llm slot resolves to ``(<slot>, agent)`` so an
    operator-chosen slot (e.g. the memory extraction slot) is addressable without a
    hardcoded entry. Unknown / non-prefixed names return None (caller leaves the body
    model untouched).
    """
    canonical = DEFAULT_CHAINS.get(virtual_name)
    if canonical is not None:
        return canonical
    if virtual_name.startswith(_VIRTUAL_PREFIX):
        slot = virtual_name[len(_VIRTUAL_PREFIX) :]
        if slot and any(_slot_matches_role(s, slot) for s in slots):
            return (slot, _ANCHOR_ROLE)
    return None


@dataclass(frozen=True)
class SlotView:
    """Minimal view of one enabled llm slot, drawn from slot config."""

    name: str
    role: str | None
    device: str  # "gpu-vulkan" | "gpu-rocm" | "cpu" | "npu"
    model_id: str
    context_length: int


@dataclass(frozen=True)
class Resolution:
    model_id: str
    context_length: int
    matched_role: str | None  # role that matched a loaded slot, or None on fallback
    fallback: bool  # True => nothing in the chain was loaded; caller should ensure-load


def _slot_matches_role(slot: SlotView, role: str) -> bool:
    """Authoritative role binding: device for npu, role tag (else name) for primary/utility."""
    if role == "npu":
        return slot.device == "npu" or (slot.role or "").lower() == "npu"
    effective = (slot.role or slot.name).lower()
    return effective == role


def _configured_primary(slots: list[SlotView]) -> SlotView | None:
    # ADR-0023: the anchor is the `agent` role. (`chat`/`primary` are retired;
    # kept here only as a transition courtesy for a box mid-migration whose
    # canonical slot hasn't been reseeded yet.)
    for role in (_ANCHOR_ROLE, "chat", "primary"):
        for s in slots:
            if _slot_matches_role(s, role):
                return s
    # last-resort: first enabled llm slot if none is tagged/named agent.
    return slots[0] if slots else None


def resolve_chain(
    virtual_name: str,
    slots: list[SlotView],
    loaded: set[str],
) -> Resolution | None:
    """Resolve a virtual name to a live slot's physical model id.

    Returns ``None`` if ``virtual_name`` is not a known virtual name. Otherwise
    always returns a ``Resolution`` (falling back to the configured primary,
    ``fallback=True``, when no chain role is currently loaded).
    """
    chain = _chain_for(virtual_name, slots)
    if chain is None:
        return None

    for role in chain:
        for slot in slots:
            # Contract: both sides are the canonical model_id, compared exactly.
            # The async wrapper passes the loaded model ids verbatim — exact
            # match is intended, do NOT lowercase.
            if _slot_matches_role(slot, role) and slot.model_id in loaded:
                return Resolution(slot.model_id, slot.context_length, role, fallback=False)

    primary = _configured_primary(slots)
    if primary is not None:
        return Resolution(primary.model_id, primary.context_length, None, fallback=True)
    # No slots at all: degrade to a bare model id so the caller can still 503 cleanly.
    return Resolution("", 0, None, fallback=True)


class LiveSlotResolver:
    """Async wrapper around ``resolve_chain``.

    ``slot_views_provider`` returns the current list of ``SlotView`` (built from
    slot config). ``loaded_models_provider`` returns the set of currently-loaded
    model ids derived from container slot state — no extra polling.
    """

    def __init__(
        self,
        slot_views_provider: Callable[[], list[SlotView]],
        loaded_models_provider: Callable[[], set[str]],
    ) -> None:
        self._views = slot_views_provider
        self._loaded = loaded_models_provider

    async def resolve(self, model_name: str) -> Resolution | None:
        # ADR-0023 §2: any `hal0/<slot>` may resolve (canonical or generalized), so
        # we can't pre-filter on DEFAULT_CHAINS membership — defer to resolve_chain,
        # which returns None for a non-virtual name or an unknown slot.
        if not model_name.startswith(_VIRTUAL_PREFIX):
            return None
        try:
            views = list(self._views() or [])
            loaded = set(self._loaded() or set())
        except Exception:
            views, loaded = [], set()
        return resolve_chain(model_name, views, loaded)

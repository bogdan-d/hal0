import pytest

from hal0.normalize.resolver import (
    DEFAULT_CHAINS,
    SlotView,
    resolve_chain,
)


def _slots():
    # ADR-0023: the anchor slot is `agent` (replaces the old `chat` anchor).
    return [
        SlotView(
            name="agent", role=None, device="gpu-vulkan", model_id="big-35b", context_length=65536
        ),
        SlotView(
            name="utility",
            role=None,
            device="gpu-vulkan",
            model_id="tiny-0.8b",
            context_length=65536,
        ),
        SlotView(
            name="npu-slot", role="npu", device="npu", model_id="qwen3-4b-FLM", context_length=32768
        ),
    ]


def test_agent_prefers_igpu_when_loaded():
    r = resolve_chain("hal0/agent", _slots(), loaded={"big-35b", "qwen3-4b-FLM"})
    assert r.model_id == "big-35b"
    assert r.context_length == 65536
    assert r.fallback is False


def test_removed_aliases_are_unknown():
    """The hal0/primary and hal0/flm aliases were removed — they are no longer
    known virtual names, so resolve_chain returns None (callers leave the body
    alone). Use the canonical hal0/agent and hal0/npu instead."""
    assert resolve_chain("hal0/primary", _slots(), loaded={"big-35b"}) is None
    assert resolve_chain("hal0/flm", _slots(), loaded={"qwen3-4b-FLM"}) is None


def test_npu_picks_npu_first_never_commandeers_agent():
    r = resolve_chain("hal0/npu", _slots(), loaded={"qwen3-4b-FLM", "big-35b"})
    assert r.model_id == "qwen3-4b-FLM"
    assert r.matched_role == "npu"


def test_npu_falls_to_utility_before_agent():
    r = resolve_chain("hal0/npu", _slots(), loaded={"tiny-0.8b", "big-35b"})
    assert r.model_id == "tiny-0.8b"
    assert r.matched_role == "utility"


def test_utility_falls_back_to_agent_anchor():
    """hal0/utility chain is (utility, agent): when utility is unloaded but the
    agent anchor is loaded, it resolves to agent (NOT npu — npu is not in the
    utility chain anymore)."""
    r = resolve_chain("hal0/utility", _slots(), loaded={"big-35b"})
    assert r.model_id == "big-35b"
    assert r.matched_role == "agent"
    assert r.fallback is False


def test_utility_prefers_utility_when_loaded():
    r = resolve_chain("hal0/utility", _slots(), loaded={"tiny-0.8b", "big-35b"})
    assert r.model_id == "tiny-0.8b"
    assert r.matched_role == "utility"


def test_role_tag_overrides_name():
    slots = [
        SlotView(
            name="coder-mini",
            role="utility",
            device="gpu-vulkan",
            model_id="cm",
            context_length=8192,
        ),
        SlotView(
            name="agent", role=None, device="gpu-vulkan", model_id="big", context_length=65536
        ),
    ]
    r = resolve_chain("hal0/utility", slots, loaded={"cm"})
    assert r.model_id == "cm"


def test_full_miss_falls_back_to_configured_primary_unloaded():
    r = resolve_chain("hal0/utility", _slots(), loaded=set())
    assert r.model_id == "big-35b"  # the `agent` anchor
    assert r.fallback is True


def test_empty_slots_degrades_to_blank_resolution():
    r = resolve_chain("hal0/agent", [], loaded=set())
    assert r is not None
    assert r.model_id == ""
    assert r.fallback is True


def test_unknown_virtual_name_returns_none():
    assert resolve_chain("hal0/nope", _slots(), loaded={"big-35b"}) is None


def test_generalized_custom_slot_resolves():
    """ADR-0023 §2: any enabled llm slot X is addressable as hal0/X with chain
    (X, agent), even without a DEFAULT_CHAINS entry."""
    slots = [
        SlotView(
            name="agent", role=None, device="gpu-vulkan", model_id="big", context_length=65536
        ),
        SlotView(
            name="coder", role=None, device="gpu-vulkan", model_id="coder-30b", context_length=32768
        ),
    ]
    r = resolve_chain("hal0/coder", slots, loaded={"coder-30b"})
    assert r is not None
    assert r.matched_role == "coder"
    assert r.model_id == "coder-30b"
    assert r.fallback is False


def test_generalized_custom_slot_falls_back_to_agent():
    """A generalized hal0/<slot> falls back to the agent anchor when the slot's
    own model isn't loaded."""
    slots = [
        SlotView(
            name="agent", role=None, device="gpu-vulkan", model_id="big", context_length=65536
        ),
        SlotView(
            name="coder", role=None, device="gpu-vulkan", model_id="coder-30b", context_length=32768
        ),
    ]
    r = resolve_chain("hal0/coder", slots, loaded={"big"})
    # agent is the second link in the (coder, agent) chain; it's loaded, so this
    # is a genuine chain match on the anchor (not a no-load fallback).
    assert r.model_id == "big"
    assert r.matched_role == "agent"
    assert r.fallback is False


def test_default_chains_shape():
    assert DEFAULT_CHAINS["hal0/agent"] == ("agent",)
    assert DEFAULT_CHAINS["hal0/npu"] == ("npu", "utility", "agent")
    assert DEFAULT_CHAINS["hal0/utility"] == ("utility", "agent")
    assert "hal0/chat" not in DEFAULT_CHAINS


@pytest.mark.asyncio
async def test_live_resolver_reads_views_and_health():
    from hal0.normalize.resolver import LiveSlotResolver, SlotView

    views = [
        SlotView(
            name="agent", role=None, device="gpu-vulkan", model_id="big", context_length=65536
        ),
        SlotView(
            name="utility", role=None, device="gpu-vulkan", model_id="tiny", context_length=65536
        ),
    ]
    resolver = LiveSlotResolver(
        slot_views_provider=lambda: views,
        loaded_models_provider=lambda: {"tiny", "big"},
    )
    res = await resolver.resolve("hal0/utility")
    assert res.model_id == "tiny"
    # passthrough: non-virtual names return None so the caller leaves the body alone
    assert await resolver.resolve("some-physical-model") is None


@pytest.mark.asyncio
async def test_live_resolver_rejects_removed_alias():
    """hal0/primary is no longer a virtual name — LiveSlotResolver returns None
    (passthrough) so the caller leaves a literal 'hal0/primary' body alone."""
    from hal0.normalize.resolver import LiveSlotResolver, SlotView

    views = [
        SlotView(
            name="agent", role=None, device="gpu-vulkan", model_id="big", context_length=65536
        ),
    ]
    resolver = LiveSlotResolver(
        slot_views_provider=lambda: views,
        loaded_models_provider=lambda: {"big"},
    )
    assert await resolver.resolve("hal0/primary") is None


def test_agent_virtual_name_resolves_to_agent_slot():
    """hal0/agent must resolve to the slot named 'agent' (the GPU MoE anchor)."""
    r = resolve_chain("hal0/agent", _slots(), loaded={"big-35b"})
    assert r is not None
    assert r.matched_role == "agent"
    assert r.model_id == "big-35b"
    assert r.fallback is False

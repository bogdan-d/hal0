"""Load-time capability fallback for a non-servable slot ``model.default``.

A seed/default may pin a model id that never landed locally under that exact
id — e.g. the catalog id ``gemma-4-12b-it`` (``upstream=hal0``, no file) while
the operator's scanned gguf registered as ``gemma-4-12b-it-ud-q4-k-xl``. Pinned
to the ghost, the slot would crash-loop on a ``--model`` path that doesn't
exist. ``SlotManager._resolve_servable_model`` falls back to a locally
registered model matching the slot's capability instead.
"""

from __future__ import annotations

from pathlib import Path

from hal0.registry.curated import CURATED_MODELS
from hal0.registry.model import Model
from hal0.registry.store import ModelRegistry
from hal0.slots.manager import SlotManager


def _add_model(home: str, *, id: str, capability: str, size_bytes: int, exists: bool = True) -> str:
    """Register a Model under HAL0_HOME, optionally materialising its file."""
    gguf = Path(home) / f"{id}.gguf"
    if exists:
        gguf.write_bytes(b"\0")
    ModelRegistry().add(
        Model(
            id=id,
            name=id,
            path=str(gguf),
            size_bytes=size_bytes,
            capabilities=[capability],
        )
    )
    return id


def _mgr() -> SlotManager:
    # _resolve_servable_model only touches static helpers + the registry, so a
    # bare instance (no __init__) is enough to exercise it.
    return SlotManager.__new__(SlotManager)


def _llm_cfg(default: str, *, device: str = "gpu-vulkan") -> dict:
    return {
        "name": "utility",
        "type": "llm",
        "device": device,
        "model": {"default": default},
    }


def test_falls_back_to_local_when_configured_id_is_ghost(tmp_hal0_home):
    real = _add_model(
        tmp_hal0_home, id="gemma-4-12b-it-ud-q4-k-xl", capability="chat", size_bytes=6_900_000_000
    )
    cfg = _llm_cfg("gemma-4-12b-it")  # ghost: not registered, not curated
    assert _mgr()._resolve_servable_model("gemma-4-12b-it", cfg) == real


def test_no_fallback_when_configured_model_is_local(tmp_hal0_home):
    _add_model(tmp_hal0_home, id="gemma-4-12b-it", capability="chat", size_bytes=6_000_000_000)
    cfg = _llm_cfg("gemma-4-12b-it")
    assert _mgr()._resolve_servable_model("gemma-4-12b-it", cfg) == "gemma-4-12b-it"


def test_no_fallback_for_npu_device_flm_tag(tmp_hal0_home):
    # A local chat model exists, but an NPU/FLM slot is served by tag — never
    # repoint it at a gguf file.
    _add_model(tmp_hal0_home, id="some-local-chat", capability="chat", size_bytes=5_000_000_000)
    cfg = _llm_cfg("gemma4-it-e2b-FLM", device="npu")
    assert _mgr()._resolve_servable_model("gemma4-it-e2b-FLM", cfg) == "gemma4-it-e2b-FLM"


def test_no_fallback_when_configured_id_is_curated_pullable(tmp_hal0_home):
    # A curated id is still-to-be-pulled; don't pre-empt the download with a
    # fallback even though a different local chat model is present.
    curated_id = next(m.id for m in CURATED_MODELS if m.capability == "chat")
    _add_model(tmp_hal0_home, id="other-local-chat", capability="chat", size_bytes=4_000_000_000)
    cfg = _llm_cfg(curated_id)
    assert _mgr()._resolve_servable_model(curated_id, cfg) == curated_id


def test_no_fallback_when_no_capability_match(tmp_hal0_home):
    # Only an embed model is local; an llm (chat) slot finds no chat fallback.
    _add_model(tmp_hal0_home, id="some-embed", capability="embed", size_bytes=500_000_000)
    cfg = _llm_cfg("gemma-4-12b-it")
    assert _mgr()._resolve_servable_model("gemma-4-12b-it", cfg) == "gemma-4-12b-it"


def test_fallback_picks_largest_on_disk(tmp_hal0_home):
    _add_model(tmp_hal0_home, id="small-chat", capability="chat", size_bytes=1_000_000_000)
    big = _add_model(tmp_hal0_home, id="big-chat", capability="chat", size_bytes=20_000_000_000)
    cfg = _llm_cfg("ghost-id")
    assert _mgr()._resolve_servable_model("ghost-id", cfg) == big


def test_fallback_skips_registered_models_with_missing_file(tmp_hal0_home):
    # Registered but the file isn't on disk → not a valid fallback target.
    _add_model(
        tmp_hal0_home, id="phantom-chat", capability="chat", size_bytes=3_000_000_000, exists=False
    )
    cfg = _llm_cfg("ghost-id")
    assert _mgr()._resolve_servable_model("ghost-id", cfg) == "ghost-id"


def test_fallback_local_model_returns_none_when_empty(tmp_hal0_home):
    assert SlotManager._fallback_local_model("chat") is None

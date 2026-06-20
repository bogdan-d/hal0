"""Tests for stack export: reference embedding + envelope + checksum.

Targeted file run:
    cd /home/halo/dev/wt/stacks-export && PYTHONPATH=src ~/dev/hal0/.venv/bin/python -m pytest tests/stacks/test_export.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hal0.config.loader import save_profiles_config
from hal0.config.schema import (
    ProfileConfig,
    ProfilesConfig,
    StackCapabilityRow,
    StackConfig,
    StackSlotEntry,
)
from hal0.registry.model import Model
from hal0.registry.store import ModelRegistry
from hal0.stacks.portable import ENVELOPE_KIND, embed_references, export_envelope


@pytest.fixture
def reg(tmp_path: Path) -> ModelRegistry:
    r = ModelRegistry(registry_dir=tmp_path / "registry")
    r.add(Model(id="ace-saber", path="/models/ace.gguf", name="Ace Saber", hf_repo="jcbtc/ace", hf_filename="ace.gguf", size_bytes=19_000_000_000, capabilities=["chat", "vision"], backends=["rocm"], mmproj="/models/ace-mmproj.gguf"))
    return r


def _stack() -> StackConfig:
    return StackConfig(
        name="Saber",
        slots=[
            StackSlotEntry(slot="agent", model="ace-saber", profile="rocm"),
            StackSlotEntry(slot="embed", capabilities=[StackCapabilityRow(child="embed", device="npu", provider="flm", model="bge-m3")]),
        ],
    )


class TestEmbedReferences:
    def test_embeds_registry_model_metadata(self, reg: ModelRegistry, tmp_hal0_home: str) -> None:
        out = embed_references(_stack(), registry=reg)
        assert "ace-saber" in out.models
        meta = out.models["ace-saber"]
        assert meta.hf_repo == "jcbtc/ace" and meta.hf_filename == "ace.gguf"
        assert meta.size_bytes == 19_000_000_000
        assert "vision" in meta.capabilities

    def test_mmproj_is_presence_marker_not_path(self, reg: ModelRegistry, tmp_hal0_home: str) -> None:
        out = embed_references(_stack(), registry=reg)
        assert out.models["ace-saber"].mmproj == "present", "host mmproj path must not leak"

    def test_missing_model_embedded_as_bare_id(self, reg: ModelRegistry, tmp_hal0_home: str) -> None:
        out = embed_references(_stack(), registry=reg)
        # bge-m3 (a capability model) is not in the registry → bare ref
        assert out.models["bge-m3"].id == "bge-m3"
        assert out.models["bge-m3"].hf_repo == ""

    def test_embeds_referenced_profile(self, reg: ModelRegistry, tmp_hal0_home: str) -> None:
        save_profiles_config(ProfilesConfig(profile={"rocm": ProfileConfig(image="ghcr.io/x:y", quant="FP4")}))
        out = embed_references(_stack(), registry=reg)
        assert "rocm" in out.profiles
        assert out.profiles["rocm"].image == "ghcr.io/x:y"

    def test_stamps_hal0_version(self, reg: ModelRegistry, tmp_hal0_home: str) -> None:
        from hal0 import __version__

        out = embed_references(_stack(), registry=reg)
        assert out.hal0_version == __version__


class TestExportEnvelope:
    def test_envelope_shape(self, reg: ModelRegistry, tmp_hal0_home: str) -> None:
        env = export_envelope(_stack(), exported_at="2026-06-20T00:00:00Z", registry=reg)
        assert env["kind"] == ENVELOPE_KIND
        assert env["schema_version"] >= 1
        assert env["exported_at"] == "2026-06-20T00:00:00Z"
        assert env["checksum"].startswith("sha256:")
        assert env["stack"]["models"]["ace-saber"]["hf_repo"] == "jcbtc/ace"

    def test_checksum_is_deterministic_and_ignores_exported_at(self, reg: ModelRegistry, tmp_hal0_home: str) -> None:
        a = export_envelope(_stack(), exported_at="2026-06-20T00:00:00Z", registry=reg)
        b = export_envelope(_stack(), exported_at="2099-01-01T00:00:00Z", registry=reg)
        assert a["checksum"] == b["checksum"], "checksum must cover the stack body only, not exported_at"

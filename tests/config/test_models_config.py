"""Tests for ModelsConfig — schema defaults + absolute-path validator."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hal0.config.schema import Hal0Config, ModelsConfig


class TestModelsConfigDefaults:
    def test_defaults(self) -> None:
        cfg = ModelsConfig()
        assert cfg.roots == ["/var/lib/hal0/models"]
        assert cfg.auto_scan_on_start is True
        assert ".gguf" in cfg.file_extensions
        assert ".safetensors" in cfg.file_extensions

    def test_attached_to_hal0_config(self) -> None:
        top = Hal0Config()
        assert isinstance(top.models, ModelsConfig)
        assert top.models.roots == ["/var/lib/hal0/models"]


class TestRootsValidator:
    def test_absolute_path_accepted(self) -> None:
        cfg = ModelsConfig(roots=["/mnt/ai-models", "/var/lib/hal0/models"])
        assert cfg.roots == ["/mnt/ai-models", "/var/lib/hal0/models"]

    def test_relative_path_rejected(self) -> None:
        with pytest.raises(ValidationError) as ei:
            ModelsConfig(roots=["models"])
        msg = str(ei.value)
        assert "absolute" in msg
        assert "models" in msg

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValidationError) as ei:
            ModelsConfig(roots=[""])
        assert "empty" in str(ei.value)

    def test_dot_relative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ModelsConfig(roots=["./local-models"])

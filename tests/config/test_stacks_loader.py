"""Unit tests for the stacks.toml loader/saver.

Targeted file run:
    ~/dev/hal0/.venv/bin/python -m pytest tests/config/test_stacks_loader.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hal0.config.loader import ConfigParseError, load_stacks_config, save_stacks_config
from hal0.config.schema import StackConfig, StackSlotEntry, StacksConfig


class TestLoadStacksConfig:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        cfg = load_stacks_config(path=tmp_path / "nonexistent.toml")
        assert cfg.stack == {}

    def test_round_trip_save_then_load(self, tmp_path: Path) -> None:
        target = tmp_path / "stacks.toml"
        cfg = StacksConfig(
            stack={
                "saber": StackConfig(
                    name="Saber",
                    description="high-speed agentic MoE",
                    slots=[StackSlotEntry(slot="agent", model="chadrock-35b-ace-saber")],
                )
            }
        )
        save_stacks_config(cfg, path=target)
        assert target.exists()
        loaded = load_stacks_config(path=target)
        assert "saber" in loaded.stack
        assert loaded.stack["saber"].name == "Saber"
        assert loaded.stack["saber"].slots[0].model == "chadrock-35b-ace-saber"

    def test_invalid_toml_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "stacks.toml"
        p.write_bytes(b"[stack\nbad toml <<<")
        with pytest.raises(ConfigParseError):
            load_stacks_config(path=p)

    def test_unknown_field_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "stacks.toml"
        p.write_bytes(b'[stack.x]\nname = "X"\nnot_a_field = "surprise"\n')
        with pytest.raises(ConfigParseError):
            load_stacks_config(path=p)

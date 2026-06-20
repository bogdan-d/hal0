"""Unit tests for StackApplyEngine.plan() — compute-only Stack→ChangeSet.

Targeted file run:
    cd /home/halo/dev/wt/stacks-apply && PYTHONPATH=src ~/dev/hal0/.venv/bin/python -m pytest tests/stacks/test_apply_plan.py -q
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from hal0.config.schema import StackConfig, StackSlotEntry
from hal0.slot_config import ChangeSet
from hal0.stacks.apply import StackApplyEngine, StackChangePlan


def _slots_dir(home: str) -> Path:
    d = Path(home) / "etc" / "hal0" / "slots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_agent_slot(home: str) -> Path:
    path = _slots_dir(home) / "agent.toml"
    path.write_text(
        "\n".join(
            [
                'name = "agent"',
                "port = 8087",
                'device = "gpu-vulkan"',
                'provider = "llama-server"',
                "enabled = true",
                'vision = false',
                "[model]",
                'default = "old-model"',
                'context_size = 8192',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _read(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _stack() -> StackConfig:
    return StackConfig(
        name="Saber",
        slots=[
            StackSlotEntry(
                slot="agent",
                model="chadrock-35b-ace-saber",
                device="gpu-rocm",
                vision=True,
            )
        ],
    )


class TestPlanComputeOnly:
    def test_plan_writes_nothing(self, tmp_hal0_home: str) -> None:
        slot_path = _write_agent_slot(tmp_hal0_home)
        before_bytes = slot_path.read_bytes()
        engine = StackApplyEngine()
        plan = engine.plan("saber", _stack())
        assert isinstance(plan, StackChangePlan)
        assert isinstance(plan.change_set, ChangeSet)
        assert slot_path.read_bytes() == before_bytes, "plan() must not touch disk"

    def test_before_matches_disk(self, tmp_hal0_home: str) -> None:
        slot_path = _write_agent_slot(tmp_hal0_home)
        plan = StackApplyEngine().plan("saber", _stack())
        by_path = {fs.path: fs.data for fs in plan.change_set.before}
        assert by_path[slot_path] == _read(slot_path)


class TestReconciliation:
    def test_after_sets_model_device_backend_vision(self, tmp_hal0_home: str) -> None:
        slot_path = _write_agent_slot(tmp_hal0_home)
        plan = StackApplyEngine().plan("saber", _stack())
        after = {fs.path: fs.data for fs in plan.change_set.after}[slot_path]
        assert after["model"]["default"] == "chadrock-35b-ace-saber"
        assert after["model"]["context_size"] == 8192, "sibling [model] keys must survive deep-merge"
        assert after["device"] == "gpu-rocm"
        assert after["backend"] == "rocm", "legacy backend alias written via model_meta"
        assert after["vision"] is True

    def test_changed_true_when_model_differs(self, tmp_hal0_home: str) -> None:
        _write_agent_slot(tmp_hal0_home)
        assert StackApplyEngine().plan("saber", _stack()).change_set.changed is True

    def test_missing_slot_file_is_skipped(self, tmp_hal0_home: str) -> None:
        # No agent.toml on disk → slot creation is out of 2a scope → after == before (None).
        _slots_dir(tmp_hal0_home)  # dir exists, file does not
        plan = StackApplyEngine().plan("saber", _stack())
        assert plan.change_set.changed is False
        assert all(fs.data is None for fs in plan.change_set.before)

    def test_summary_lists_changed_slot(self, tmp_hal0_home: str) -> None:
        _write_agent_slot(tmp_hal0_home)
        plan = StackApplyEngine().plan("saber", _stack())
        assert any("agent" in line for line in plan.summary)

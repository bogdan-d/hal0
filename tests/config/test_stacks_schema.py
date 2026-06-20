"""Unit tests for the Stack schema models.

Targeted file run:
    ~/dev/hal0/.venv/bin/python -m pytest tests/config/test_stacks_schema.py -q
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hal0.config.schema import (
    SEED_STACKS,
    STACK_SCHEMA_VERSION_CURRENT,
    StackCapabilityRow,
    StackConfig,
    StackModelMeta,
    StackSlotEntry,
    StacksConfig,
)


class TestStackModelMeta:
    def test_minimal_requires_id(self) -> None:
        m = StackModelMeta(id="chadrock-35b-ace-saber")
        assert m.id == "chadrock-35b-ace-saber"
        assert m.size_bytes == 0
        assert m.capabilities == []
        assert m.mmproj is None

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            StackModelMeta(id="   ")

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            StackModelMeta(id="m1", path="/mnt/ai-models/x.gguf")  # path is machine-specific, excluded

    def test_id_is_stripped(self) -> None:
        assert StackModelMeta(id="  chadrock-35b-ace-saber  ").id == "chadrock-35b-ace-saber"


class TestStackCapabilityRow:
    def test_valid_row(self) -> None:
        r = StackCapabilityRow(child="embed", device="npu", provider="flm", model="bge-m3")
        assert r.enabled is True

    def test_bad_device_raises(self) -> None:
        with pytest.raises(ValidationError):
            StackCapabilityRow(child="embed", device="quantum", provider="flm", model="bge-m3")


class TestStackSlotEntry:
    def test_minimal_requires_slot(self) -> None:
        e = StackSlotEntry(slot="agent")
        assert e.slot == "agent"
        assert e.vision is False
        assert e.capabilities == []

    def test_bad_slot_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            StackSlotEntry(slot="Agent Slot!")

    def test_bad_device_raises(self) -> None:
        with pytest.raises(ValidationError):
            StackSlotEntry(slot="agent", device="gpu-quantum")


class TestStackConfig:
    def test_defaults(self) -> None:
        s = StackConfig()
        assert s.name == ""
        assert s.schema_version == STACK_SCHEMA_VERSION_CURRENT
        assert s.slots == []
        assert s.profiles == {}
        assert s.models == {}

    def test_full_round_trip_through_dict(self) -> None:
        s = StackConfig(
            name="Saber",
            description="high-speed agentic MoE",
            slots=[StackSlotEntry(slot="agent", model="chadrock-35b-ace-saber")],
            models={"chadrock-35b-ace-saber": StackModelMeta(id="chadrock-35b-ace-saber")},
        )
        dumped = s.model_dump(mode="python", exclude_none=True)
        again = StackConfig.model_validate(dumped)
        assert again.slots[0].slot == "agent"
        assert again.models["chadrock-35b-ace-saber"].id == "chadrock-35b-ace-saber"

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            StackConfig(surprise="nope")


class TestStacksConfig:
    def test_empty_default(self) -> None:
        c = StacksConfig()
        assert c.stack == {}

    def test_keyed_by_slug(self) -> None:
        c = StacksConfig(stack={"saber": StackConfig(name="Saber")})
        assert c.stack["saber"].name == "Saber"


class TestSeedStacks:
    def test_seed_stacks_is_empty_until_pr6(self) -> None:
        assert SEED_STACKS == {}

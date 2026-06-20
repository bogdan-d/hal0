"""Unit tests for StacksCatalog CRUD + guards.

Targeted file run:
    ~/dev/hal0/.venv/bin/python -m pytest tests/stacks/test_stacks_catalog.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hal0.config import schema
from hal0.config.schema import StackConfig, StackSlotEntry
from hal0.errors import Conflict, NotFound
from hal0.stacks import ResolvedStack, StacksCatalog


@pytest.fixture
def catalog(tmp_path: Path) -> StacksCatalog:
    return StacksCatalog(path=tmp_path / "stacks.toml")


def _saber() -> StackConfig:
    return StackConfig(
        name="Saber",
        description="high-speed agentic MoE",
        slots=[StackSlotEntry(slot="agent", model="chadrock-35b-ace-saber")],
    )


class TestCreateAndRead:
    def test_create_then_resolve(self, catalog: StacksCatalog) -> None:
        created = catalog.create("saber", _saber())
        assert isinstance(created, ResolvedStack)
        assert created.slug == "saber"
        assert created.seed is False
        got = catalog.resolve("saber")
        assert got.name == "Saber"
        assert got.slots[0].slot == "agent"

    def test_create_then_list(self, catalog: StacksCatalog) -> None:
        catalog.create("saber", _saber())
        slugs = [r.slug for r in catalog.list()]
        assert slugs == ["saber"]

    def test_create_duplicate_raises_conflict(self, catalog: StacksCatalog) -> None:
        catalog.create("saber", _saber())
        with pytest.raises(Conflict):
            catalog.create("saber", _saber())

    def test_create_invalid_slug_raises_conflict(self, catalog: StacksCatalog) -> None:
        with pytest.raises(Conflict):
            catalog.create("Saber Slot!", _saber())

    def test_resolve_missing_raises_not_found(self, catalog: StacksCatalog) -> None:
        with pytest.raises(NotFound):
            catalog.resolve("ghost")


class TestUpdateAndDelete:
    def test_update_replaces(self, catalog: StacksCatalog) -> None:
        catalog.create("saber", _saber())
        updated = catalog.update("saber", StackConfig(name="Saber v2"))
        assert updated.name == "Saber v2"
        assert updated.slots == []

    def test_update_missing_raises_not_found(self, catalog: StacksCatalog) -> None:
        with pytest.raises(NotFound):
            catalog.update("ghost", _saber())

    def test_delete(self, catalog: StacksCatalog) -> None:
        catalog.create("saber", _saber())
        catalog.delete("saber")
        assert catalog.list() == []

    def test_delete_missing_raises_not_found(self, catalog: StacksCatalog) -> None:
        with pytest.raises(NotFound):
            catalog.delete("ghost")


class TestSeedGuard:
    def test_seed_stack_is_immutable(self, catalog: StacksCatalog, monkeypatch: pytest.MonkeyPatch) -> None:
        # Inject a seed entry so the guard has something to protect (SEED_STACKS
        # is empty until PR-6). The catalog reads SEED_STACKS from the schema
        # module. No create() call: update()/delete() run _guard_custom() FIRST,
        # so they raise on a seed slug regardless of whether it is on disk —
        # and load_stacks_config already surfaces seeds when the file is absent.
        monkeypatch.setitem(schema.SEED_STACKS, "saber", _saber())
        with pytest.raises(Conflict):
            catalog.update("saber", StackConfig(name="hijack"))
        with pytest.raises(Conflict):
            catalog.delete("saber")


class TestPersistence:
    def test_persists_across_catalog_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "stacks.toml"
        StacksCatalog(path=path).create("saber", _saber())
        # Fresh catalog instance reads the written file.
        assert any(r.slug == "saber" for r in StacksCatalog(path=path).list())

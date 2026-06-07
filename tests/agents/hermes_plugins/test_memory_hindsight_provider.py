"""Renamed hal0-memory Hermes plugin (P5-H)."""

from __future__ import annotations

import inspect

from hal0.agents.hermes.plugins.memory_hindsight._client import Hal0MemoryClient
from hal0.agents.hermes.plugins.memory_hindsight.provider import Hal0MemoryProvider


def test_provider_name_is_hal0_memory():
    assert Hal0MemoryProvider().name == "hal0-memory"


def test_no_dataset_field_ever_sent():
    src = inspect.getsource(Hal0MemoryClient.add)
    assert '"dataset"' not in src and "'dataset'" not in src

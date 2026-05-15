"""Shared pytest fixtures for hal0 tests."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hal0.api import create_app

pytest_plugins = ()


@pytest.fixture(scope="function")
def app() -> FastAPI:
    """Return a fresh FastAPI app instance."""
    return create_app()


@pytest.fixture(scope="function")
def client(app: FastAPI) -> TestClient:
    """Return a TestClient wrapping a fresh app instance."""
    return TestClient(app)


@pytest.fixture(scope="function")
def tmp_hal0_home(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> str:
    """Set HAL0_HOME to a temporary directory for filesystem isolation."""
    home = str(tmp_path)
    monkeypatch.setenv("HAL0_HOME", home)
    return home

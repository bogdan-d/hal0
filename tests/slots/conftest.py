"""Pytest fixtures and marker registration for the slots subtree."""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register the integration marker so --strict-markers stays clean.

    The integration suite needs hal0-slot@.service installed on the host
    and is intended for CI / release-gate runs only.  See PLAN.md §10.
    """
    config.addinivalue_line(
        "markers",
        "integration: end-to-end slot lifecycle tests requiring a real "
        "hal0-slot@.service installation",
    )

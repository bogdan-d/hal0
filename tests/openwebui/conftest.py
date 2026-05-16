"""Pytest marker registration for the openwebui subtree.

The ``integration`` marker is shared with tests/slots — both subtrees use
``-m integration`` to opt into CI-only end-to-end tests.  Each subtree
registers the marker locally so ``--strict-markers`` stays clean even if
only one subtree's tests are collected.
"""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: end-to-end tests requiring docker + network "
        "(skipped on the dev VM unless docker is reachable)",
    )

"""Verify that all Phase 0 stub endpoints return 501 with a structured error envelope.

Envelope schema:
    {"error": {"code": "system.not_implemented", "message": "...", "details": {}}}
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# (method, path) pairs — all should 501 with the structured envelope.
# Endpoints leave this list as they get wired up; the remaining ones are
# all genuine Phase 2+ surfaces (installer, updater, logs streaming, etc.)
_STUB_ENDPOINTS = [
    ("GET", "/api/slots/foo"),
    ("POST", "/api/models"),
    ("GET", "/api/logs/api"),
    ("GET", "/api/upstreams"),
    ("GET", "/api/updates/check"),
    ("GET", "/api/install/state"),
]


def _assert_envelope(body: dict, path: str) -> None:
    """Assert the response body matches the structured error envelope."""
    assert "error" in body, f"{path}: response missing 'error' key: {body}"
    err = body["error"]
    assert "code" in err, f"{path}: error envelope missing 'code': {err}"
    assert "message" in err, f"{path}: error envelope missing 'message': {err}"
    assert "details" in err, f"{path}: error envelope missing 'details': {err}"
    assert err["code"] == "system.not_implemented", (
        f"{path}: expected code='system.not_implemented', got {err['code']!r}"
    )
    assert isinstance(err["message"], str) and err["message"], (
        f"{path}: 'message' must be a non-empty string, got {err['message']!r}"
    )
    assert isinstance(err["details"], dict), (
        f"{path}: 'details' must be a dict, got {type(err['details'])}"
    )


@pytest.mark.parametrize("method,path", _STUB_ENDPOINTS)
def test_stub_returns_501_envelope(client: TestClient, method: str, path: str) -> None:
    """Stub endpoint returns 501 with well-formed error envelope."""
    response = client.request(method, path)
    assert response.status_code == 501, (
        f"{method} {path}: expected 501, got {response.status_code}. Body: {response.text[:200]}"
    )
    body = response.json()
    _assert_envelope(body, f"{method} {path}")

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
    # /api/logs, /api/settings, /api/install/state, /api/updates/check
    # are now wired (see Team C's wave). The remaining 501 surfaces all
    # live behind their owner's wave with a typed envelope code; they
    # are covered by their own per-team route tests rather than this
    # generic system.not_implemented assertion.
    #
    # Intentionally empty: no Phase-0 stubs remain in the route surface
    # that still emit ``code: "system.not_implemented"``.
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
    """Stub endpoint returns 501 with well-formed envelope (currently none)."""
    response = client.request(method, path)
    assert response.status_code == 501, (
        f"{method} {path}: expected 501, got {response.status_code}. Body: {response.text[:200]}"
    )
    body = response.json()
    _assert_envelope(body, f"{method} {path}")


# Endpoints owned by other teams' waves keep a typed-domain 501 (NOT
# system.not_implemented) so the UI can branch on the specific code.
# Asserting the typed code prevents an accidental regression to the
# generic stub envelope.
# NOTE: the v0.1 model-pull wave (Team B) wired this surface live —
# the endpoints below now return real responses instead of typed 501s.
# This list is intentionally empty in the v1 release; kept as a slot for
# future waves so an introduced 501 doesn't slip back to the generic
# ``system.not_implemented`` envelope.
_TYPED_PENDING_ENDPOINTS: list[tuple[str, str, str]] = []


@pytest.mark.skipif(
    not _TYPED_PENDING_ENDPOINTS,
    reason="no typed-pending endpoints in this release",
)
@pytest.mark.parametrize("method,path,code", _TYPED_PENDING_ENDPOINTS)
def test_typed_pending_endpoint_returns_domain_code(
    client: TestClient, method: str, path: str, code: str
) -> None:
    """Cross-team pending endpoints carry their domain code, not the generic stub."""
    response = client.request(method, path)
    assert response.status_code == 501, (
        f"{method} {path}: expected 501, got {response.status_code}. Body: {response.text[:200]}"
    )
    body = response.json()
    assert body["error"]["code"] == code, (
        f"{method} {path}: expected code={code!r}, got {body['error']['code']!r}"
    )

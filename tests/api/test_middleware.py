"""Tests for hal0 API middleware.

Covers:
- X-Request-ID propagation (request_id middleware)
- Unhandled Exception → 500 structured envelope
- Hal0Error subclass → correct status + envelope code
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hal0.api.middleware.error_codes import Hal0Error
from hal0.api.middleware.error_codes import install as install_error_codes
from hal0.api.middleware.request_id import install as install_request_id


def _make_test_app() -> FastAPI:
    """Build a minimal FastAPI app with both middleware pieces installed."""
    app = FastAPI()
    install_request_id(app)
    install_error_codes(app)
    return app


def test_request_id_added(client: TestClient) -> None:
    """Response always contains x-request-id header."""
    response = client.get("/api/status")
    assert "x-request-id" in response.headers, (
        "Expected 'x-request-id' header in response, got: " + str(dict(response.headers))
    )
    assert response.headers["x-request-id"], "x-request-id header must be non-empty"


def test_request_id_echoed(client: TestClient) -> None:
    """Custom x-request-id on the request is echoed back in the response."""
    custom_id = "test-req-id-abc123"
    response = client.get("/api/status", headers={"x-request-id": custom_id})
    assert response.headers.get("x-request-id") == custom_id, (
        f"Expected echoed x-request-id={custom_id!r}, got {response.headers.get('x-request-id')!r}"
    )


def test_unhandled_exception_returns_envelope() -> None:
    """A route that raises a plain Exception returns 500 with system.internal envelope."""
    app = _make_test_app()

    @app.get("/test/boom")
    async def _boom() -> None:
        raise RuntimeError("unexpected failure")

    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.get("/test/boom")

    assert response.status_code == 500, (
        f"Expected 500 from unhandled exception, got {response.status_code}"
    )
    body = response.json()
    assert "error" in body, f"Missing 'error' key: {body}"
    assert body["error"]["code"] == "system.internal", (
        f"Expected code='system.internal', got {body['error']['code']!r}"
    )


def test_hal0_error_envelope() -> None:
    """A route that raises a Hal0Error subclass returns the correct status and code."""
    app = _make_test_app()

    class TeapotError(Hal0Error):
        code = "test.example"
        status = 418

    @app.get("/test/teapot")
    async def _teapot() -> None:
        raise TeapotError("I am a teapot")

    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.get("/test/teapot")

    assert response.status_code == 418, f"Expected 418 from TeapotError, got {response.status_code}"
    body = response.json()
    assert "error" in body, f"Missing 'error' key: {body}"
    assert body["error"]["code"] == "test.example", (
        f"Expected code='test.example', got {body['error']['code']!r}"
    )
    assert body["error"]["message"] == "I am a teapot", (
        f"Expected message='I am a teapot', got {body['error']['message']!r}"
    )

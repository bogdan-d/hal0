"""Tests for /api/config/urls.

The dashboard reads this endpoint on mount to discover the right
hostnames for the API and the OpenWebUI Chat link, plus a runtime flag
saying whether the OpenWebUI unit is actually up.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_urls_returns_three_required_keys(client: TestClient) -> None:
    """All three keys land in the response, with the documented types."""
    resp = client.get("/api/config/urls")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {"api", "openwebui", "openwebui_enabled"}
    assert isinstance(body["api"], str) and body["api"].startswith("http://")
    assert isinstance(body["openwebui"], str) and body["openwebui"].startswith("http://")
    assert isinstance(body["openwebui_enabled"], bool)


def test_urls_use_request_host(client: TestClient) -> None:
    """Both URLs echo the hostname the request came in on (not localhost)."""
    resp = client.get("/api/config/urls", headers={"host": "hal0-test.lan:8080"})
    assert resp.status_code == 200
    body = resp.json()
    assert "hal0-test.lan" in body["api"], body
    assert "hal0-test.lan" in body["openwebui"], body
    # Port still :3001 for the chat link, regardless of how the API was reached.
    assert body["openwebui"].endswith(":3001")


def test_urls_api_port_honours_env(
    monkeypatch,
    client: TestClient,
) -> None:
    """HAL0_PORT shifts the api URL port but not the openwebui port."""
    monkeypatch.setenv("HAL0_PORT", "9090")
    resp = client.get("/api/config/urls")
    body = resp.json()
    assert body["api"].endswith(":9090"), body["api"]
    assert body["openwebui"].endswith(":3001"), body["openwebui"]


def test_urls_openwebui_enabled_false_when_systemctl_missing(
    monkeypatch,
    client: TestClient,
) -> None:
    """If systemctl can't be exec'd, openwebui_enabled is False (not an error)."""
    # Point PATH at an empty dir so systemctl isn't found.
    monkeypatch.setenv("PATH", "/nonexistent-path-for-tests")
    resp = client.get("/api/config/urls")
    assert resp.status_code == 200
    assert resp.json()["openwebui_enabled"] is False


def test_urls_path_based_when_behind_proxy(client: TestClient) -> None:
    """When X-Forwarded-* is present, openwebui is a /chat/ path on the
    forwarded host — not a direct host:3001 URL that bypasses the proxy
    and skips X-Forwarded-Email injection."""
    resp = client.get(
        "/api/config/urls",
        headers={
            "x-forwarded-host": "ai-dev.thinmint.dev",
            "x-forwarded-proto": "https",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["openwebui"] == "https://ai-dev.thinmint.dev/chat/", body
    assert body["api"] == "https://ai-dev.thinmint.dev", body

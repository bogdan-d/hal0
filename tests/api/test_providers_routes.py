"""Tests for /api/upstreams and /api/providers routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from hal0.upstreams.registry import Upstream


def _seed_upstreams(client: TestClient) -> None:
    reg = client.app.state.upstreams
    # Clear any auto-registered entries so the test is deterministic.
    for u in list(reg.list()):
        reg.remove(u.name)
    reg.add(
        Upstream(
            name="primary",
            kind="slot",
            url="http://127.0.0.1:8081/v1",
            slot_name="primary",
        )
    )
    reg.add(
        Upstream(
            name="openrouter",
            kind="remote",
            url="https://openrouter.ai/api/v1",
            auth_value_env="OPENROUTER_API_KEY",
        )
    )


def test_list_upstreams_returns_registered_entries(client: TestClient) -> None:
    _seed_upstreams(client)
    response = client.get("/api/upstreams")
    assert response.status_code == 200, response.text
    body = response.json()
    names = {u["name"] for u in body}
    assert {"primary", "openrouter"} <= names
    for u in body:
        assert "name" in u and "kind" in u and "url" in u
        # Secrets never leak — only the env-var name appears.
        assert "auth_value" not in u
        if u["name"] == "openrouter":
            assert u["auth_value_env"] == "OPENROUTER_API_KEY"
            assert u["auth_configured"] is True
            assert u["kind"] == "remote"


def test_get_upstream_by_name(client: TestClient) -> None:
    _seed_upstreams(client)
    response = client.get("/api/upstreams/primary")
    assert response.status_code == 200
    assert response.json()["name"] == "primary"


def test_get_upstream_404(client: TestClient) -> None:
    _seed_upstreams(client)
    response = client.get("/api/upstreams/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "upstream.not_found"


def test_providers_excludes_slot_kind(client: TestClient) -> None:
    _seed_upstreams(client)
    response = client.get("/api/providers")
    assert response.status_code == 200
    names = {u["name"] for u in response.json()}
    assert "openrouter" in names
    assert "primary" not in names  # slot upstreams aren't "providers"


def test_providers_catalog_has_known_entries(client: TestClient) -> None:
    response = client.get("/api/providers/catalog")
    assert response.status_code == 200
    catalog = response.json()
    # Anthropic + OpenAI + OpenRouter are part of the built-in catalog;
    # at minimum the catalog must be non-empty.
    assert isinstance(catalog, dict) and len(catalog) > 0

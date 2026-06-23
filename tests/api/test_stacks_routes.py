"""Tests for the /api/stacks route surface (PR-4).

Covers catalog CRUD, declarative apply (dry-run diff + commit→converge),
export → import round-trip, snapshot, and seed-immutability — exercised through
the real ``create_app()`` + ``TestClient`` so the lifespan-wired registry /
slot-manager / orchestrator are in play.

Run targeted:
    PYTHONPATH=src .venv-test/bin/python -m pytest tests/api/test_stacks_routes.py -q
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hal0.api import create_app
from hal0.config import schema
from hal0.config.schema import StackConfig

# ── helpers ────────────────────────────────────────────────────────────────────


def _seed_slot_toml(home: str, name: str, *, model: str = "", port: int = 8090) -> Path:
    """Write a minimal slot TOML so the apply engine has a file to reconcile."""
    root = Path(home) / "etc" / "hal0" / "slots"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.toml"
    body = f'[slot]\nname = "{name}"\nport = {port}\n'
    if model:
        body += f'\n[model]\ndefault = "{model}"\n'
    path.write_text(body, encoding="utf-8")
    return path


def _stack_body(name: str = "Coding", slots: list[dict] | None = None) -> dict:
    return {"name": name, "description": "test stack", "slots": slots or []}


# ── fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def app(tmp_hal0_home: str) -> FastAPI:
    """Fresh app; tmp_hal0_home means no stacks.toml → empty catalog."""
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


# ── GET (list) ─────────────────────────────────────────────────────────────────


def test_list_ships_seed_catalog(client: TestClient) -> None:
    # Fresh install (no stacks.toml) → the built-in seed stacks (PR-6).
    r = client.get("/api/stacks")
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is None
    assert body["drift"] == "none"
    slugs = {s["slug"] for s in body["stacks"]}
    assert {"saber", "forge", "pi"} <= slugs
    assert all(s["seed"] is True for s in body["stacks"] if s["slug"] in {"saber", "forge", "pi"})


# ── POST (create) ──────────────────────────────────────────────────────────────


def test_create_201_and_listed(client: TestClient) -> None:
    r = client.post("/api/stacks", json={"slug": "coding", "stack": _stack_body()})
    assert r.status_code == 201
    body = r.json()
    assert body["slug"] == "coding"
    assert body["name"] == "Coding"
    assert body["seed"] is False
    assert body["active"] is False
    listed = client.get("/api/stacks").json()["stacks"]
    assert any(s["slug"] == "coding" for s in listed)


def test_create_persists_across_reload(tmp_hal0_home: str) -> None:
    with TestClient(create_app()) as c1:
        assert (
            c1.post("/api/stacks", json={"slug": "persist", "stack": _stack_body()}).status_code
            == 201
        )
    with TestClient(create_app()) as c2:
        listed = c2.get("/api/stacks").json()["stacks"]
    assert any(s["slug"] == "persist" for s in listed)


def test_create_duplicate_409(client: TestClient) -> None:
    client.post("/api/stacks", json={"slug": "coding", "stack": _stack_body()})
    r = client.post("/api/stacks", json={"slug": "coding", "stack": _stack_body()})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "stacks.exists"


def test_create_invalid_slug_409(client: TestClient) -> None:
    r = client.post("/api/stacks", json={"slug": "Bad Slug!", "stack": _stack_body()})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "stacks.invalid_name"


def test_create_unknown_body_field_422(client: TestClient) -> None:
    r = client.post(
        "/api/stacks",
        json={"slug": "coding", "stack": _stack_body(), "bogus": 1},
    )
    assert r.status_code == 422


# ── GET (detail) ───────────────────────────────────────────────────────────────


def test_get_detail_200(client: TestClient) -> None:
    client.post("/api/stacks", json={"slug": "coding", "stack": _stack_body()})
    r = client.get("/api/stacks/coding")
    assert r.status_code == 200
    assert r.json()["name"] == "Coding"


def test_get_missing_404(client: TestClient) -> None:
    r = client.get("/api/stacks/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "stacks.not_found"


# ── PUT (update) ───────────────────────────────────────────────────────────────


def test_update_200_persists(client: TestClient) -> None:
    client.post("/api/stacks", json={"slug": "coding", "stack": _stack_body()})
    r = client.put("/api/stacks/coding", json=_stack_body(name="Coding v2"))
    assert r.status_code == 200
    assert r.json()["name"] == "Coding v2"
    assert client.get("/api/stacks/coding").json()["name"] == "Coding v2"


def test_update_missing_404(client: TestClient) -> None:
    r = client.put("/api/stacks/nope", json=_stack_body())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "stacks.not_found"


# ── DELETE ─────────────────────────────────────────────────────────────────────


def test_delete_204(client: TestClient) -> None:
    client.post("/api/stacks", json={"slug": "coding", "stack": _stack_body()})
    assert client.delete("/api/stacks/coding").status_code == 204
    slugs = {s["slug"] for s in client.get("/api/stacks").json()["stacks"]}
    assert "coding" not in slugs  # seeds remain; the custom stack is gone


def test_delete_missing_404(client: TestClient) -> None:
    r = client.delete("/api/stacks/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "stacks.not_found"


# ── seed immutability (monkeypatched seed registry) ────────────────────────────


def test_seed_immutable_put_and_delete_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(schema.SEED_STACKS, "saber", StackConfig(name="Saber"))
    put = client.put("/api/stacks/saber", json=_stack_body())
    assert put.status_code == 409
    assert put.json()["error"]["code"] == "stacks.seed_immutable"
    delete = client.delete("/api/stacks/saber")
    assert delete.status_code == 409
    assert delete.json()["error"]["code"] == "stacks.seed_immutable"


# ── apply (dry-run) ────────────────────────────────────────────────────────────


def test_apply_dry_run_shows_diff(tmp_hal0_home: str) -> None:
    _seed_slot_toml(tmp_hal0_home, "agent", model="old-model")
    with TestClient(create_app()) as c:
        c.post(
            "/api/stacks",
            json={
                "slug": "coding",
                "stack": _stack_body(slots=[{"slot": "agent", "model": "new-model"}]),
            },
        )
        r = c.post("/api/stacks/coding/apply", params={"dry_run": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    row = next(x for x in body["changes"] if x["slot"] == "agent")
    assert row["before_model"] == "old-model"
    assert row["after_model"] == "new-model"
    assert row["changed"] is True


# ── apply (commit + converge with injected fakes) ──────────────────────────────


def test_apply_commit_converges_and_sets_active(app: FastAPI, tmp_hal0_home: str) -> None:
    _seed_slot_toml(tmp_hal0_home, "agent", model="old-model")
    with TestClient(app) as c:
        c.post(
            "/api/stacks",
            json={
                "slug": "coding",
                "stack": _stack_body(slots=[{"slot": "agent", "model": "new-model"}]),
            },
        )
        # Inject fakes so converge() drives no real containers: empty live
        # snapshot → the agent slot is "loaded".
        fake_sm = AsyncMock()
        fake_sm.list = AsyncMock(return_value=[])
        app.state.slot_manager = fake_sm
        app.state.capability_orchestrator = AsyncMock()

        r = c.post("/api/stacks/coding/apply")
        assert r.status_code == 200
        body = r.json()
        assert body["dry_run"] is False
        assert "agent" in body["converged"]["loaded"]
        fake_sm.load.assert_awaited()

        # Active pointer + clean drift (live toml == applied projection).
        listed = c.get("/api/stacks").json()
        assert listed["active"] == "coding"
        assert listed["drift"] == "clean"
        active_item = next(s for s in listed["stacks"] if s["slug"] == "coding")
        assert active_item["active"] is True
        assert active_item["drift"] == "clean"


# ── export / import round-trip ─────────────────────────────────────────────────


def test_export_import_round_trip(client: TestClient) -> None:
    client.post("/api/stacks", json={"slug": "coding", "stack": _stack_body()})
    env = client.post("/api/stacks/coding/export").json()
    assert env["kind"] == "hal0.stack"
    assert env["checksum"].startswith("sha256:")

    # dry-run import validates + checksum-verifies, creates nothing.
    dry = client.post("/api/stacks/import", json={"dry_run": True, "envelope": env})
    assert dry.status_code == 200
    assert dry.json()["valid"] is True
    assert dry.json()["checksum_ok"] is True

    # commit creates a clone under a new slug.
    commit = client.post("/api/stacks/import", json={"slug": "coding-copy", "envelope": env})
    assert commit.status_code == 200
    assert commit.json()["stack"]["slug"] == "coding-copy"
    assert any(s["slug"] == "coding-copy" for s in client.get("/api/stacks").json()["stacks"])


def test_import_commit_without_slug_400(client: TestClient) -> None:
    client.post("/api/stacks", json={"slug": "coding", "stack": _stack_body()})
    env = client.post("/api/stacks/coding/export").json()
    r = client.post("/api/stacks/import", json={"envelope": env})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "stacks.import_no_slug"


def test_import_bad_envelope_400(client: TestClient) -> None:
    r = client.post("/api/stacks/import", json={"dry_run": True, "envelope": {"kind": "nope"}})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "stacks.bad_envelope"


# ── snapshot ───────────────────────────────────────────────────────────────────


def test_snapshot_returns_unsaved_config(tmp_hal0_home: str) -> None:
    _seed_slot_toml(tmp_hal0_home, "agent", model="some-model")
    with TestClient(create_app()) as c:
        r = c.post("/api/stacks/snapshot", json={"name": "from-live"})
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is False
    assert body["stack"]["name"] == "from-live"
    assert any(s["slot"] == "agent" for s in body["stack"]["slots"])


def test_snapshot_with_slug_persists(tmp_hal0_home: str) -> None:
    _seed_slot_toml(tmp_hal0_home, "agent", model="some-model")
    with TestClient(create_app()) as c:
        r = c.post("/api/stacks/snapshot", json={"name": "snap", "slug": "snap-1"})
        assert r.status_code == 200
        assert r.json()["created"] is True
        assert any(s["slug"] == "snap-1" for s in c.get("/api/stacks").json()["stacks"])

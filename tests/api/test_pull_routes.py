"""Route tests for /api/models/{id}/pull* and /api/install/pick-default.

The real ``run_pull`` body is patched so tests don't hit HuggingFace —
we exercise the routing surface, job state machine, and slot TOML
write, not the HTTP streaming itself (that's tested separately in
``tests/registry/test_pull.py``).
"""

from __future__ import annotations

import time
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hal0.api import create_app
from hal0.registry import pull as pull_module
from hal0.registry.pull import PullJob

# ── shared fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def app_isolated(tmp_hal0_home: str) -> Iterator[FastAPI]:
    """Build an app under HAL0_HOME so atomic writes are tmp-scoped."""
    yield create_app()


@pytest.fixture
def client_isolated(app_isolated: FastAPI) -> Iterator[TestClient]:
    with TestClient(app_isolated) as c:
        yield c


@pytest.fixture
def fake_run_pull(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Patch run_pull to record calls + drive job state synchronously.

    Returns a list the test can inspect to assert what was scheduled.
    The fake transitions the job straight to ``completed`` so SSE / status
    routes see a terminal frame on their first poll.
    """
    calls: list[dict[str, Any]] = []

    async def fake(job: PullJob, *, hf_repo: str, hf_file: str, **kw: Any) -> None:
        calls.append({"job": job, "hf_repo": hf_repo, "hf_file": hf_file, **kw})
        job.state = "running"
        job.bytes_total = 1024
        job.bytes_downloaded = 1024
        job.state = "completed"
        job.finished_at = time.time()
        # Pulse so any awaiting SSE generator wakes.
        job._signal()

    monkeypatch.setattr(pull_module, "run_pull", fake)
    # The routes import run_pull at module load — also patch their
    # binding so the fake reaches the BackgroundTasks invocation.
    from hal0.api.routes import installer as installer_routes
    from hal0.api.routes import models as model_routes

    monkeypatch.setattr(installer_routes, "run_pull", fake)
    monkeypatch.setattr(model_routes, "run_pull", fake)
    return calls


# ── POST /api/models/{id}/pull ──────────────────────────────────────────────


def test_pull_returns_job_handle_and_kicks_background_task(
    client_isolated: TestClient, fake_run_pull: list[dict[str, Any]]
) -> None:
    """A curated id resolves to its HF coordinates; a job handle returns."""
    r = client_isolated.post("/api/models/qwen3-4b/pull")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["model_id"] == "qwen3-4b"
    assert body["state"] in ("queued", "running", "completed")
    assert body["hf_repo"].startswith("Qwen/")
    assert body["hf_file"].endswith(".gguf")
    # Background task ran (TestClient drains background tasks before
    # returning).
    assert len(fake_run_pull) == 1
    assert fake_run_pull[0]["hf_repo"] == body["hf_repo"]


def test_pull_unknown_model_returns_invalid_source(
    client_isolated: TestClient, fake_run_pull: list[dict[str, Any]]
) -> None:
    """A model with no HF coordinates and no curated entry → 422."""
    r = client_isolated.post("/api/models/nonsense-id/pull")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "model.invalid_source"
    assert fake_run_pull == []


def test_pull_idempotent_when_already_running(
    client_isolated: TestClient,
    app_isolated: FastAPI,
    fake_run_pull: list[dict[str, Any]],
) -> None:
    """Two POSTs back-to-back don't spawn two jobs."""
    # First call completes via the fake. Manually re-set state to
    # ``running`` so the second call hits the "already in flight" branch.
    client_isolated.post("/api/models/qwen3-4b/pull")
    jobs = app_isolated.state.model_pull_jobs
    jobs["qwen3-4b"].state = "running"
    r = client_isolated.post("/api/models/qwen3-4b/pull")
    body = r.json()
    assert body.get("resumed") is True


def test_pull_status_returns_job_dict(
    client_isolated: TestClient, fake_run_pull: list[dict[str, Any]]
) -> None:
    client_isolated.post("/api/models/qwen3-4b/pull")
    r = client_isolated.get("/api/models/qwen3-4b/pull/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model_id"] == "qwen3-4b"
    assert body["state"] == "completed"
    assert body["bytes_downloaded"] == body["bytes_total"]


def test_pull_status_404_when_no_job(client_isolated: TestClient) -> None:
    r = client_isolated.get("/api/models/qwen3-4b/pull/status")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "model.pull_job_not_found"


def test_pull_cancel_flips_flag(
    client_isolated: TestClient,
    app_isolated: FastAPI,
    fake_run_pull: list[dict[str, Any]],
) -> None:
    """Cancelling an in-flight job sets the cancel flag."""
    client_isolated.post("/api/models/qwen3-4b/pull")
    jobs = app_isolated.state.model_pull_jobs
    jobs["qwen3-4b"].state = "running"  # simulate live download
    r = client_isolated.post("/api/models/qwen3-4b/pull/cancel")
    assert r.status_code == 200, r.text
    assert jobs["qwen3-4b"].cancel_requested is True


# ── POST /api/install/pick-default ─────────────────────────────────────────


def test_pick_default_creates_registry_entry_and_writes_slot(
    client_isolated: TestClient,
    tmp_hal0_home: str,
    app_isolated: FastAPI,
    fake_run_pull: list[dict[str, Any]],
) -> None:
    """pick-default seeds the registry, writes the slot TOML, queues a pull."""
    r = client_isolated.post(
        "/api/install/pick-default",
        json={"model_id": "phi3-mini", "slot": "primary"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model_id"] == "phi3-mini"
    assert body["slot"] == "primary"
    assert "pull_job_id" in body
    assert body["next"].startswith("poll /api/models/")

    # Registry row exists with curated metadata.
    registry = app_isolated.state.model_registry
    entry = registry.get("phi3-mini")
    assert entry.hf_repo == "microsoft/Phi-3-mini-4k-instruct-gguf"
    assert entry.license == "MIT"

    # Slot TOML carries model.default = "phi3-mini".
    slot_toml = Path(tmp_hal0_home) / "etc" / "hal0" / "slots" / "primary.toml"
    assert slot_toml.exists()
    with open(slot_toml, "rb") as f:
        cfg = tomllib.load(f)
    assert cfg["model"]["default"] == "phi3-mini"

    # The pull was queued.
    assert len(fake_run_pull) == 1


def test_pick_default_unknown_id_returns_404(
    client_isolated: TestClient, fake_run_pull: list[dict[str, Any]]
) -> None:
    r = client_isolated.post(
        "/api/install/pick-default",
        json={"model_id": "not-a-curated-id", "slot": "primary"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "install.curated_not_found"
    assert fake_run_pull == []


def test_pick_default_defaults_slot_to_primary(
    client_isolated: TestClient,
    tmp_hal0_home: str,
    fake_run_pull: list[dict[str, Any]],
) -> None:
    """Body without ``slot`` falls back to ``primary``."""
    r = client_isolated.post("/api/install/pick-default", json={"model_id": "qwen3-4b"})
    assert r.status_code == 200, r.text
    assert r.json()["slot"] == "primary"


def test_pick_default_preserves_existing_slot_port_and_backend(
    client_isolated: TestClient,
    tmp_hal0_home: str,
    fake_run_pull: list[dict[str, Any]],
) -> None:
    """A pre-existing slot TOML's port/backend survive the model.default rewrite."""
    slot_dir = Path(tmp_hal0_home) / "etc" / "hal0" / "slots"
    slot_dir.mkdir(parents=True, exist_ok=True)
    (slot_dir / "primary.toml").write_text(
        'name = "primary"\nport = 9999\nbackend = "rocm"\nprovider = "llama-server"\n',
        encoding="utf-8",
    )

    r = client_isolated.post(
        "/api/install/pick-default",
        json={"model_id": "qwen3-4b"},
    )
    assert r.status_code == 200, r.text

    with open(slot_dir / "primary.toml", "rb") as f:
        cfg = tomllib.load(f)
    assert cfg["port"] == 9999
    assert cfg["backend"] == "rocm"
    assert cfg["model"]["default"] == "qwen3-4b"

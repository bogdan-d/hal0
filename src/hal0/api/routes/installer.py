"""First-run wizard backend endpoints (mounted under /api/install).

These are the *server* contract that the FirstRun wizard UI (Team B/E)
consumes; the wizard itself is a separate Vue view.

Endpoints:
    GET  /api/install/state    — surface first-run + has-models +
                                 has-default-slot + openwebui-running
                                 flags so the dashboard can decide
                                 whether to route to FirstRun.
    POST /api/install/probe    — re-run the hardware probe and write
                                 ``/etc/hal0/hardware.json`` atomically.
    POST /api/install/complete — marker call after the wizard finishes;
                                 writes ``/var/lib/hal0/.first_run_done``
                                 so subsequent boots skip the wizard.

The curated-models picker and the actual model pull (POST /pick-default)
are Team B's wave (HF streaming download + SSE progress) — left as 501
stubs with a clearer ``code: "model.pull_pending"`` envelope so the UI
can detect "feature not landed yet" vs "broken".
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from hal0.api.middleware.error_codes import Hal0Error
from hal0.config import paths
from hal0.hardware.probe import HardwareProbe

router = APIRouter()


class ModelPullPending(Hal0Error):
    """501 marker for endpoints Team B owns (model download flow)."""

    code = "model.pull_pending"
    status = 501


def _first_run_sentinel() -> Path:
    """Path to the marker file written after the FirstRun wizard finishes."""
    return paths.var_lib() / ".first_run_done"


def _models_dir_populated() -> bool:
    """True if ``/var/lib/hal0/models/`` exists and contains at least one file."""
    d = paths.models_dir()
    if not d.exists():
        return False
    try:
        for entry in d.iterdir():
            # A nested directory or a model file both count as "populated"
            # — fresh installs have the directory missing or empty.
            if entry.name.startswith("."):
                continue
            return True
    except OSError:
        return False
    return False


def _has_default_slot() -> bool:
    """True if /etc/hal0/slots/primary.toml exists."""
    return (paths.slots_config_dir() / "primary.toml").exists()


async def _openwebui_running() -> bool:
    """Best-effort: ask systemd whether hal0-openwebui.service is active.

    Returns False on hosts without systemctl (CI, mac dev boxes) and on
    any subprocess failure — this flag drives a UI hint, not a hard gate,
    so we tolerate missing infra.
    """
    if shutil.which("systemctl") is None:
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "is-active",
            "hal0-openwebui.service",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
    except (TimeoutError, OSError):
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()  # type: ignore[has-type]
        return False
    return stdout.decode("utf-8", errors="replace").strip() == "active"


@router.get("/state")
async def install_state(request: Request) -> dict[str, Any]:
    """Return the dashboard's first-run gating state.

    Shape::

        {
            "first_run": true,
            "has_models": false,
            "has_default_slot": false,
            "openwebui_running": false,
            "sentinel_path": "/var/lib/hal0/.first_run_done"
        }

    ``first_run`` is true when ``/var/lib/hal0/models/`` is empty AND the
    sentinel hasn't been written. Either condition flipping false hides
    the FirstRun wizard.
    """
    has_models = _models_dir_populated()
    sentinel = _first_run_sentinel()
    sentinel_present = sentinel.exists()
    has_default = _has_default_slot()
    openwebui = await _openwebui_running()
    first_run = (not has_models) and (not sentinel_present)
    return {
        "first_run": first_run,
        "has_models": has_models,
        "has_default_slot": has_default,
        "openwebui_running": openwebui,
        "sentinel_path": str(sentinel),
    }


@router.post("/probe")
async def install_probe(request: Request) -> dict[str, Any]:
    """Re-run the hardware probe and rewrite ``/etc/hal0/hardware.json``.

    Returns the freshly-probed HardwareInfo as JSON. Uses the existing
    ``HardwareProbe.write()`` which already does atomic tempfile+replace.
    """
    probe: HardwareProbe = getattr(request.app.state, "hardware_probe", None) or HardwareProbe()
    info = await probe.probe_async()
    # ``write()`` raises HardwareProbeError on disk failures, which is a
    # Hal0Error subclass — let the envelope middleware surface it.
    target = probe.write(info)
    # Cache on app.state so subsequent /api/hardware reads can skip the
    # re-probe round-trip.
    request.app.state.hardware_info = info
    return {
        "hardware": info.model_dump(mode="json"),
        "path": str(target),
    }


@router.post("/complete")
async def install_complete(request: Request) -> dict[str, Any]:
    """Mark the FirstRun wizard as complete by writing the sentinel.

    Atomic: tempfile + os.replace in the parent directory so a partial
    write can't leave a half-written marker. Idempotent — re-calling
    after the sentinel already exists is a no-op.
    """
    sentinel = _first_run_sentinel()
    sentinel.parent.mkdir(parents=True, exist_ok=True)

    payload = "first_run_done\n"
    tmp_path: Path | None = None
    try:
        fd, tmp_str = tempfile.mkstemp(
            prefix=f".{sentinel.name}.",
            suffix=".tmp",
            dir=sentinel.parent,
        )
        tmp_path = Path(tmp_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            with contextlib.suppress(OSError):
                os.close(fd)
            raise
        os.replace(tmp_path, sentinel)
        tmp_path = None
    except OSError as exc:
        raise Hal0Error(
            f"could not write first-run sentinel: {exc}",
            details={"path": str(sentinel), "error": str(exc)},
        ) from exc
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)

    return {"first_run": False, "sentinel_path": str(sentinel)}


# ── Team B's domain — model picker + pull ──────────────────────────────────
# Curated picker list + model download flow lands with Team B's wave
# (HF streaming download + SSE progress). Surface area kept as typed 501s
# so the FirstRun wizard can detect "not implemented yet" vs "broken".


@router.get("/curated-models")
async def curated_models() -> list[dict[str, object]]:
    """Curated model picker list — Team B's wave (v0.2)."""
    raise ModelPullPending(
        "curated model picker not yet implemented; expected in v0.2 wave",
        details={"owner": "team-b"},
    )


@router.post("/pick-default")
async def pick_default() -> dict[str, object]:
    """Download a curated model + assign to primary slot — Team B's wave."""
    raise ModelPullPending(
        "default-model pick not yet implemented; expected in v0.2 wave",
        details={"owner": "team-b"},
    )

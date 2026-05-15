"""MoonshineProvider — Moonshine STT (speech-to-text) backend.

Moonshine runs CPU/Vulkan and exposes an OpenAI-compatible
/v1/audio/transcriptions endpoint plus a WebSocket /v1/audio/stream
for live PCM16 transcription.

# NOTE: The haloai server (lib/voice/moonshine_server.py, ~250 lines)
# IS the FastAPI app — hal0 does not port that code; the hal0 toolbox
# image bundles it. This Provider only wraps it: it returns the
# systemd ExecStart, the ContainerSpec, the health probe, and an
# infer() passthrough.  Streaming WS is handled directly by the
# Dispatcher, not by this Provider's infer().

Toolbox image: ghcr.io/hal0-dev/hal0-toolbox-moonshine:v1 (PLAN.md §12).
Port target: new hal0 provider wrapping haloai lib/voice/moonshine_server.py.
"""

from __future__ import annotations

from typing import Any

import httpx

from hal0.api.middleware.error_codes import Hal0Error
from hal0.providers.base import ContainerSpec, Provider

# ── Toolbox image ──────────────────────────────────────────────────────────────
_HAL0_MOONSHINE_IMAGE = "ghcr.io/hal0-dev/hal0-toolbox-moonshine:v1"

# Moonshine server entrypoint inside the toolbox image.
# NOTE: The toolbox image ENTRYPOINT runs the FastAPI server; this binary
# path is the bare-process fallback for `start_cmd()` and integration
# tests outside a container.
_MOONSHINE_BIN = "/usr/local/bin/moonshine-server"

# Default Moonshine model archs ranked by quality. "small_streaming" is
# haloai's default and the recommended starting point.
_DEFAULT_MODEL_ARCH = "small_streaming"

# ── Timeouts ───────────────────────────────────────────────────────────────────
_HEALTH_TIMEOUT = httpx.Timeout(5.0)
_INFER_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=10.0)


class MoonshineHealthError(Hal0Error):
    """Moonshine health probe failed."""

    code = "slot.not_ready"
    status = 503


class MoonshineInferError(Hal0Error):
    """Moonshine inference call failed."""

    code = "dispatch.upstream_failed"
    status = 502


class MoonshineProvider(Provider):
    """Provider for the Moonshine streaming STT backend.

    Endpoints (served by the in-container FastAPI app):
      - GET  /health                  -> {status, model_loaded, model_arch}
      - GET  /v1/models               -> [{id: "moonshine-<arch>-en"}]
      - POST /v1/audio/transcriptions -> OpenAI-compat multipart upload
      - WS   /v1/audio/stream         -> live PCM16 @ 16kHz mono

    # NOTE: WS streaming is dispatched by the hal0 Dispatcher directly;
    # this Provider only implements the unary infer() path so CLI smoke
    # tests can hit /v1/audio/transcriptions with a wav file.
    """

    name = "moonshine"

    # ── Env / argv ─────────────────────────────────────────────────────────────

    def build_env(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> dict[str, str]:
        """Build HAL0_* env vars for a Moonshine slot."""
        port = slot_cfg.get("port") or slot_cfg.get("slot", {}).get("port", 8089)
        model_path = model_info.get("path", "")
        # model_arch can come from the registry (model_info.model_arch) or
        # be set per-slot (slot_cfg.model_arch). Slot wins; default small.
        model_arch = (
            slot_cfg.get("model_arch") or model_info.get("model_arch") or _DEFAULT_MODEL_ARCH
        )

        return {
            "HAL0_MOONSHINE_MODEL_PATH": str(model_path),
            "HAL0_MOONSHINE_MODEL_ARCH": str(model_arch),
            "HAL0_PORT": str(port),
            "HAL0_MOONSHINE_BIN": _MOONSHINE_BIN,
        }

    def start_cmd(self, env: dict[str, str]) -> list[str]:
        """argv for moonshine-server invocation.

        Matches the argparse contract in
        haloai lib/voice/moonshine_server.py:main().
        """
        binary = env.get("HAL0_MOONSHINE_BIN", _MOONSHINE_BIN)
        return [
            binary,
            "--model_path",
            env["HAL0_MOONSHINE_MODEL_PATH"],
            "--model_arch",
            env["HAL0_MOONSHINE_MODEL_ARCH"],
            "--port",
            env["HAL0_PORT"],
            "--host",
            "0.0.0.0",
        ]

    # ── Image / container spec ─────────────────────────────────────────────────

    def image_ref(self, _slot_cfg: dict[str, Any]) -> str:
        """Return the Moonshine toolbox image reference."""
        return _HAL0_MOONSHINE_IMAGE

    def container_spec(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> ContainerSpec:
        """Build a ContainerSpec for Moonshine in the toolbox image.

        Moonshine is CPU/Vulkan; no NPU or ROCm needed. We still pass
        /dev/dri so Vulkan-accelerated decode/encode paths inside the
        container can use the iGPU when present.
        """
        env = self.build_env(slot_cfg, model_info)
        port = int(env["HAL0_PORT"])

        # NOTE: The toolbox image ENTRYPOINT runs the FastAPI app;
        # command[] is args only.
        command: list[str] = [
            "--model_path",
            env["HAL0_MOONSHINE_MODEL_PATH"],
            "--model_arch",
            env["HAL0_MOONSHINE_MODEL_ARCH"],
            "--port",
            str(port),
            "--host",
            "0.0.0.0",
        ]

        # Bind-mount the model directory so the in-container path matches host.
        paths = slot_cfg.get("_paths", {}) or {}
        models_base = paths.get("models_base", "/var/lib/hal0/models")
        mounts: list[tuple[str, str]] = [(models_base, models_base)]

        return ContainerSpec(
            image=self.image_ref(slot_cfg),
            command=command,
            env={},
            mounts=mounts,
            devices=["/dev/dri"],
            cap_add=[],
            security_opt=["seccomp=unconfined", "apparmor=unconfined"],
            group_add=["video", "render"],
            port=port,
            network_mode="host",
            extra_args=[],
        )

    # ── Health / infer ─────────────────────────────────────────────────────────

    async def health(self, port: int) -> dict[str, Any]:
        """Health probe: GET /health, checking model_loaded=true.

        Moonshine's /health returns a richer payload than llama-server's;
        we surface model_loaded as the readiness signal. No sentinel
        inference probe here — STT doesn't have a trivially cheap
        round-trip, and the Tier 1 fix is FLM-specific (it's a chat
        backend with a fast max_tokens=1 path).

        # TIER2: If we later see flakiness, add a 100ms silence-wav
        # round-trip to /v1/audio/transcriptions. Not required for v1.
        """
        url = f"http://127.0.0.1:{port}/health"
        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return {
                        "ok": False,
                        "status": f"http_{resp.status_code}",
                        "detail": resp.text[:200],
                    }
                body = resp.json()
                model_loaded = bool(body.get("model_loaded"))
                if not model_loaded:
                    return {
                        "ok": False,
                        "status": "model_not_loaded",
                        "model": body.get("model_id"),
                    }
                return {
                    "ok": True,
                    "status": "ready",
                    "model": body.get("model_id"),
                    "model_arch": body.get("model_arch"),
                }
        except httpx.HTTPError as exc:
            return {"ok": False, "status": "http_error", "detail": str(exc)}
        except Exception as exc:
            return {"ok": False, "status": "exception", "detail": str(exc)}

    async def infer(self, port: int, body: dict[str, Any]) -> dict[str, Any]:
        """Passthrough /v1/audio/transcriptions (unary, non-streaming).

        Expects body to be a dict with at minimum:
          {"file": <bytes>, "model": <model_id>, "response_format": "json"|"verbose_json"}
        Streaming WS is handled by the Dispatcher, not this method.

        # NOTE: Moonshine's transcriptions endpoint is multipart/form-data,
        # not JSON. We adapt the dict here into a multipart upload.
        """
        url = f"http://127.0.0.1:{port}/v1/audio/transcriptions"

        # Pull the file bytes; everything else becomes form data.
        file_bytes = body.get("file")
        if file_bytes is None:
            raise MoonshineInferError(
                "moonshine.infer requires body['file'] (raw audio bytes)",
                details={"port": port},
            )
        form: dict[str, Any] = {}
        for k, v in body.items():
            if k == "file":
                continue
            form[k] = (None, str(v))
        files = {"file": ("audio.wav", file_bytes, "application/octet-stream")}

        try:
            async with httpx.AsyncClient(timeout=_INFER_TIMEOUT) as client:
                resp = await client.post(url, data=form, files=files)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            raise MoonshineInferError(
                f"moonshine returned HTTP {exc.response.status_code}",
                details={"port": port, "status_code": exc.response.status_code},
            ) from exc
        except httpx.HTTPError as exc:
            raise MoonshineInferError(
                f"moonshine transport error: {exc}",
                details={"port": port},
            ) from exc

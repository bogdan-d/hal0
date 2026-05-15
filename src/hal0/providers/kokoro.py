"""KokoroProvider — Kokoro-82M TTS (text-to-speech) backend.

Kokoro runs CPU (ONNX) or GPU (PyTorch) and exposes an OpenAI-compatible
/v1/audio/speech endpoint.  This is the canonical local-TTS pairing for
hal0's voice flows.

# NOTE: Unlike llama_server / flm, haloai had no clean Kokoro Provider
# reference — Kokoro shipped as an ad-hoc slot. This Provider is
# written fresh against the OpenAI TTS contract.

Upstream reference image:
  ghcr.io/remsky/kokoro-fastapi-cpu:latest (CPU ONNX, well-maintained)
  ghcr.io/remsky/kokoro-fastapi-gpu:latest (PyTorch + CUDA)

# NOTE: hal0 ships its own toolbox build under
#   ghcr.io/hal0ai/hal0-toolbox-kokoro:v1
# which wraps remsky/Kokoro-FastAPI with hal0's runtime conventions
# (model paths, port binding, healthcheck shape). Until hal0ai GHCR
# is provisioned (PLAN.md §17 Risks), the toolbox build can be sourced
# from the upstream image.

# NOTE: The Kokoro-FastAPI server defaults to port 8880; hal0 slots
# bind to whatever slot_cfg["port"] says (default 8090 for TTS slots).

See PLAN.md §1 (v1 ships — Kokoro TTS) and §12 (toolbox images).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from hal0.errors import Hal0Error
from hal0.providers._gpu import resolve_gpu_group_ids
from hal0.providers.base import ContainerSpec, Provider

# ── Toolbox image ──────────────────────────────────────────────────────────────
_HAL0_KOKORO_IMAGE = "ghcr.io/hal0ai/hal0-toolbox-kokoro:v1"

# Bare-process entrypoint inside the toolbox image (mirrors remsky's
# FastAPI app launch). Used for start_cmd() outside containers and for
# integration tests.
_KOKORO_BIN = "/usr/local/bin/kokoro-server"

# Default OpenAI-compat voice id (remsky uses "af_bella" as the default
# female-American voice; ranked highest in the upstream benchmark).
_DEFAULT_VOICE = "af_bella"

# Default Kokoro model id reported via /v1/models.
_DEFAULT_MODEL_ID = "kokoro"

# ── Timeouts ───────────────────────────────────────────────────────────────────
_HEALTH_TIMEOUT = httpx.Timeout(5.0)
_INFER_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=10.0)


class KokoroHealthError(Hal0Error):
    """Kokoro health probe failed."""

    code = "slot.not_ready"
    status = 503


class KokoroInferError(Hal0Error):
    """Kokoro inference call failed."""

    code = "dispatch.upstream_failed"
    status = 502


class KokoroProvider(Provider):
    """Provider for the Kokoro-82M TTS backend.

    Endpoints:
      - GET  /health                       -> {status: "ok", ...}
      - GET  /v1/models                    -> [{id: "kokoro"}]
      - POST /v1/audio/speech              -> OpenAI-compat TTS (returns audio bytes)
      - GET  /v1/audio/voices              -> remsky extension, voice list
    """

    name = "kokoro"

    # ── Env / argv ─────────────────────────────────────────────────────────────

    def build_env(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> dict[str, str]:
        """Build HAL0_* env vars for a Kokoro slot."""
        port = slot_cfg.get("port") or slot_cfg.get("slot", {}).get("port", 8090)
        model_path = model_info.get("path", "")
        default_voice = (
            slot_cfg.get("default_voice") or model_info.get("default_voice") or _DEFAULT_VOICE
        )
        # Slot backend selects between CPU and GPU runtime inside the
        # toolbox image. Default CPU since hal0 targets low-RAM home boxes.
        backend = slot_cfg.get("backend") or slot_cfg.get("slot", {}).get("backend") or "cpu"

        return {
            "HAL0_KOKORO_MODEL_PATH": str(model_path),
            "HAL0_KOKORO_DEFAULT_VOICE": str(default_voice),
            "HAL0_KOKORO_BACKEND": str(backend),
            "HAL0_PORT": str(port),
            "HAL0_KOKORO_BIN": _KOKORO_BIN,
        }

    def start_cmd(self, env: dict[str, str]) -> list[str]:
        """argv for kokoro-server invocation.

        Mirrors the remsky/Kokoro-FastAPI launch contract: pass model
        directory + port + host.
        """
        binary = env.get("HAL0_KOKORO_BIN", _KOKORO_BIN)
        return [
            binary,
            "--model_path",
            env["HAL0_KOKORO_MODEL_PATH"],
            "--default_voice",
            env["HAL0_KOKORO_DEFAULT_VOICE"],
            "--port",
            env["HAL0_PORT"],
            "--host",
            "0.0.0.0",
        ]

    # ── Image / container spec ─────────────────────────────────────────────────

    def image_ref(self, slot_cfg: dict[str, Any]) -> str:
        """Resolve the Kokoro toolbox image.

        Resolution order (matches ``llama_server.image_ref``):
          1. ``slot_cfg["image"]`` — explicit override from slot TOML.
          2. ``HAL0_TOOLBOX_IMAGE_KOKORO`` env var.
          3. The default ``ghcr.io/hal0ai/hal0-toolbox-kokoro:v1``.
        """
        override = slot_cfg.get("image") or slot_cfg.get("slot", {}).get("image")
        if override:
            return str(override)
        env_override = os.environ.get("HAL0_TOOLBOX_IMAGE_KOKORO", "").strip()
        if env_override:
            return env_override
        return _HAL0_KOKORO_IMAGE

    def container_spec(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> ContainerSpec:
        """Build a ContainerSpec for Kokoro in the toolbox image.

        CPU runtime needs no devices; GPU runtime would want /dev/dri
        plus the CUDA libs (deferred until GPU is wired in v0.2).
        """
        env = self.build_env(slot_cfg, model_info)
        port = int(env["HAL0_PORT"])

        command: list[str] = [
            "--model_path",
            env["HAL0_KOKORO_MODEL_PATH"],
            "--default_voice",
            env["HAL0_KOKORO_DEFAULT_VOICE"],
            "--port",
            str(port),
            "--host",
            "0.0.0.0",
        ]

        paths = slot_cfg.get("_paths", {}) or {}
        models_base = paths.get("models_base", "/var/lib/hal0/models")
        mounts: list[tuple[str, str]] = [(models_base, models_base)]

        # CPU-only by default; pass /dev/dri only if backend=="vulkan" so
        # the in-container ONNX VulkanEP can find the iGPU.
        backend = env["HAL0_KOKORO_BACKEND"]
        devices: list[str] = []
        group_add: list[str] = []
        if backend == "vulkan":
            devices = ["/dev/dri"]
            group_add = [str(g) for g in resolve_gpu_group_ids()]

        return ContainerSpec(
            image=self.image_ref(slot_cfg),
            command=command,
            env={},
            mounts=mounts,
            devices=devices,
            cap_add=[],
            security_opt=["seccomp=unconfined", "apparmor=unconfined"],
            group_add=group_add,
            port=port,
            network_mode="host",
            extra_args=[],
        )

    # ── Health / infer ─────────────────────────────────────────────────────────

    async def health(self, port: int) -> dict[str, Any]:
        """Health probe: GET /health + GET /v1/models (non-empty).

        Kokoro doesn't have a cheap inference round-trip option (the
        smallest synthesis is ~50ms of audio + model warmup), so we
        require /health=ok AND /v1/models non-empty as the readiness
        signal.

        # TIER2: a one-character synthesis probe ("a") is cheap enough
        # to add if /v1/models ever lies about readiness in practice;
        # not required for v1.
        """
        health_url = f"http://127.0.0.1:{port}/health"
        models_url = f"http://127.0.0.1:{port}/v1/models"
        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
                health_resp = await client.get(health_url)
                if health_resp.status_code != 200:
                    return {
                        "ok": False,
                        "status": f"health_http_{health_resp.status_code}",
                        "detail": health_resp.text[:200],
                    }
                # Some Kokoro builds return {"status": "ok"}; others just 200.
                try:
                    health_body = health_resp.json()
                except Exception:
                    health_body = {}
                if health_body and health_body.get("status") not in (None, "ok", "ready"):
                    return {
                        "ok": False,
                        "status": "health_not_ok",
                        "detail": str(health_body.get("status")),
                    }
                # /v1/models must report a populated model list.
                models_resp = await client.get(models_url)
                if models_resp.status_code != 200:
                    return {
                        "ok": False,
                        "status": f"models_http_{models_resp.status_code}",
                    }
                models_data = models_resp.json()
                models = models_data.get("data", [])
                if not models:
                    return {"ok": False, "status": "models_endpoint_empty"}
                return {
                    "ok": True,
                    "status": "ready",
                    "model": models[0].get("id", _DEFAULT_MODEL_ID),
                }
        except httpx.HTTPError as exc:
            return {"ok": False, "status": "http_error", "detail": str(exc)}
        except Exception as exc:
            return {"ok": False, "status": "exception", "detail": str(exc)}

    async def infer(self, port: int, body: dict[str, Any]) -> dict[str, Any]:
        """Passthrough /v1/audio/speech to Kokoro.

        Body shape (OpenAI-compat):
            {
              "model":           "kokoro",
              "input":           "Hello, world.",
              "voice":           "af_bella",
              "response_format": "mp3" | "wav" | "opus" | "flac" | "pcm",
              "speed":           1.0,
            }

        # NOTE: Kokoro's /v1/audio/speech returns raw audio bytes, NOT
        # JSON. We wrap the result in a hal0 envelope:
        #   {"audio": <bytes>, "content_type": "audio/<fmt>", "voice": "..."}
        # so the Dispatcher can stream the bytes back to the caller.
        """
        url = f"http://127.0.0.1:{port}/v1/audio/speech"
        try:
            async with httpx.AsyncClient(timeout=_INFER_TIMEOUT) as client:
                resp = await client.post(url, json=body)
                resp.raise_for_status()
                return {
                    "audio": resp.content,
                    "content_type": resp.headers.get("content-type", "audio/mpeg"),
                    "voice": body.get("voice", _DEFAULT_VOICE),
                    "format": body.get("response_format", "mp3"),
                }
        except httpx.HTTPStatusError as exc:
            raise KokoroInferError(
                f"kokoro returned HTTP {exc.response.status_code}",
                details={"port": port, "status_code": exc.response.status_code},
            ) from exc
        except httpx.HTTPError as exc:
            raise KokoroInferError(
                f"kokoro transport error: {exc}",
                details={"port": port},
            ) from exc

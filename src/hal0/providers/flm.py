"""FLMProvider — AMD NPU (XDNA2) inference backend.

FLM (Flexible Language Model) targets the AMD Strix Halo NPU.  Optional —
only loaded on hardware where the NPU driver is present and the FLM
toolbox image is available.

Capabilities: chat, embed, ASR multiplexed on one NPU (see PLAN.md §1).
Toolbox image: ghcr.io/hal0-dev/hal0-toolbox-flm:v1 (PLAN.md §12).

Port target: haloai lib/providers/flm.py (106 lines).
See PLAN.md §5 Tier 1 — health probe must verify a real inference
round-trip, not just a non-empty /v1/models list (that's the bug at
haloai lib/slots.py:899-920).

# NOTE: haloai's FLM multiplexes ASR + embed on the same NPU device
# via flags `load_asr` / `load_embed` in slot defaults. The runtime
# serializes execution (single shared compute), but multiplexing avoids
# duplicating model RAM on the NPU. Empirical test 2026-05-07 confirmed
# multi-process FLM coexists but provides no parallelism gain — so the
# single-multiplexed-process design wins on RAM and is what we port.
"""

from __future__ import annotations

from typing import Any

import httpx

from hal0.api.middleware.error_codes import Hal0Error
from hal0.providers.base import ContainerSpec, Provider

# ── Toolbox image ──────────────────────────────────────────────────────────────
_HAL0_FLM_IMAGE = "ghcr.io/hal0-dev/hal0-toolbox-flm:v1"

# ── Timeouts ───────────────────────────────────────────────────────────────────
# TIER1: separate health budget from infer budget.
_HEALTH_TIMEOUT = httpx.Timeout(5.0)
# The sentinel completion can take a moment on cold NPU; give it a
# more generous read window than llama-server.
_HEALTH_INFER_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)
_INFER_TIMEOUT = httpx.Timeout(connect=5.0, read=300.0, write=10.0, pool=10.0)


class FLMHealthError(Hal0Error):
    """FLM health probe failed (typed for the error envelope)."""

    code = "slot.not_ready"
    status = 503


class FLMInferError(Hal0Error):
    """FLM inference call failed."""

    code = "dispatch.upstream_failed"
    status = 502


def _load_flm_backend_meta() -> dict[str, Any]:
    """Return FLM backend profile [backend] dict, or {}.

    # NOTE: see llama_server._load_backend_meta — Phase 5 hook.
    """
    return {}


class FLMProvider(Provider):
    """Provider for the AMD NPU FLM backend.

    Health probe REQUIRES a real /v1/chat/completions round-trip with
    max_tokens=1, not just a populated /v1/models list. This is the
    Tier 1 fix for the haloai lib/slots.py:899-920 bug.
    """

    name = "flm"

    # ── Env / argv ─────────────────────────────────────────────────────────────

    def build_env(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> dict[str, str]:
        """Build HAL0_* env vars for an FLM slot.

        Ported from haloai lib/providers/flm.py. Renames HALOAI_* → HAL0_*.
        """
        port = slot_cfg.get("port") or slot_cfg.get("slot", {}).get("port", 8086)
        ctx = slot_cfg.get("ctx_size") or slot_cfg.get("defaults", {}).get("context_size", 65536)
        flm_tag = model_info.get("flm_tag") or model_info.get("_model_key") or "qwen3.5:0.8b"

        meta = _load_flm_backend_meta()
        binary = meta.get("binary", "/usr/local/bin/flm")

        # FLM single-process multiplex flags.
        defaults = slot_cfg.get("defaults", {})
        load_asr = "1" if defaults.get("load_asr") else "0"
        load_embed = "1" if defaults.get("load_embed") else "0"

        return {
            "HAL0_FLM_TAG": str(flm_tag),
            "HAL0_PORT": str(port),
            "HAL0_FLM_CTX": str(ctx),
            "HAL0_FLM_BINARY": binary,
            "HAL0_FLM_LOAD_ASR": load_asr,
            "HAL0_FLM_LOAD_EMBED": load_embed,
        }

    def start_cmd(self, env: dict[str, str]) -> list[str]:
        """Return argv for `flm serve`."""
        binary = env.get("HAL0_FLM_BINARY", "/usr/local/bin/flm")
        return [
            binary,
            "serve",
            env["HAL0_FLM_TAG"],
            "--port",
            env["HAL0_PORT"],
            "--host",
            "0.0.0.0",
            "--ctx-len",
            env["HAL0_FLM_CTX"],
        ]

    # ── Image / container spec ─────────────────────────────────────────────────

    def image_ref(self, _slot_cfg: dict[str, Any]) -> str:
        """Return the FLM toolbox image reference (single backend, no variants)."""
        return _HAL0_FLM_IMAGE

    def container_spec(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> ContainerSpec:
        """Build a ContainerSpec for FLM in the toolbox image.

        FLM needs /dev/accel for the AMD XDNA2 NPU. /dev/dri is included
        for completeness (some FLM builds expose iGPU helpers).
        """
        env = self.build_env(slot_cfg, model_info)
        port = int(env["HAL0_PORT"])

        command: list[str] = [
            "serve",
            env["HAL0_FLM_TAG"],
            "--port",
            str(port),
            "--host",
            "0.0.0.0",
            "--ctx-len",
            env["HAL0_FLM_CTX"],
        ]

        # Bind-mount the FLM model cache if configured on the slot.
        paths = slot_cfg.get("_paths", {}) or {}
        mounts: list[tuple[str, str]] = []
        flm_cache = paths.get("flm_cache")
        if flm_cache:
            mounts.append((flm_cache, flm_cache))

        return ContainerSpec(
            image=self.image_ref(slot_cfg),
            command=command,
            env={},
            mounts=mounts,
            # /dev/accel: XDNA2 NPU device node. /dev/dri: iGPU companion.
            devices=["/dev/accel", "/dev/dri"],
            cap_add=[],
            security_opt=["seccomp=unconfined", "apparmor=unconfined"],
            group_add=["video", "render"],
            port=port,
            network_mode="host",
            extra_args=[],
        )

    # ── Health / infer ─────────────────────────────────────────────────────────

    async def health(self, port: int) -> dict[str, Any]:
        """Health probe with a real inference round-trip.

        TIER1: PLAN.md §5 — the haloai version (lib/providers/flm.py)
        reported "ok" as soon as `/v1/models` returned data, even when
        the model failed to actually load on the NPU. We now require
        BOTH:
          1. non-empty /v1/models
          2. a /v1/chat/completions with max_tokens=1 returning a
             well-formed response with at least one choice

        Returns {"ok": bool, "status": str, "model": str|None, ...}.
        """
        models_url = f"http://127.0.0.1:{port}/v1/models"
        chat_url = f"http://127.0.0.1:{port}/v1/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
                # Step 1: /v1/models must be non-empty.
                models_resp = await client.get(models_url)
                models_resp.raise_for_status()
                data = models_resp.json()
                models = data.get("data", [])
                if not models:
                    return {
                        "ok": False,
                        "status": "models_endpoint_empty",
                        "detail": "/v1/models returned no entries",
                    }
                model_id = models[0].get("id")

            # Step 2: real inference round-trip.  # TIER1
            async with httpx.AsyncClient(timeout=_HEALTH_INFER_TIMEOUT) as client:
                probe_body = {
                    "model": model_id,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                    "temperature": 0.0,
                    "stream": False,
                }
                chat_resp = await client.post(chat_url, json=probe_body)
                if chat_resp.status_code != 200:
                    return {
                        "ok": False,
                        "status": f"sentinel_completion_http_{chat_resp.status_code}",
                        "detail": chat_resp.text[:200],
                        "model": model_id,
                    }
                try:
                    body = chat_resp.json()
                except Exception:
                    return {
                        "ok": False,
                        "status": "sentinel_completion_unparseable",
                        "model": model_id,
                    }
                if not body.get("choices"):
                    return {
                        "ok": False,
                        "status": "sentinel_completion_no_choices",
                        "model": model_id,
                    }
            return {"ok": True, "status": "ready", "model": model_id}
        except httpx.HTTPError as exc:
            return {"ok": False, "status": "http_error", "detail": str(exc)}
        except Exception as exc:
            # TIER1: do not silently swallow.
            return {"ok": False, "status": "exception", "detail": str(exc)}

    async def infer(self, port: int, body: dict[str, Any]) -> dict[str, Any]:
        """Passthrough /v1/chat/completions to FLM."""
        url = f"http://127.0.0.1:{port}/v1/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=_INFER_TIMEOUT) as client:
                resp = await client.post(url, json=body)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            raise FLMInferError(
                f"FLM returned HTTP {exc.response.status_code}",
                details={"port": port, "status_code": exc.response.status_code},
            ) from exc
        except httpx.HTTPError as exc:
            raise FLMInferError(
                f"FLM transport error: {exc}",
                details={"port": port},
            ) from exc

"""FLMProvider — AMD NPU (XDNA2) inference backend.

FLM (Flexible Language Model) targets the AMD Strix Halo NPU. Optional —
only loaded on hardware where the NPU driver is present and the FLM
binary tree + toolbox image are available.

Capabilities: chat, embed, ASR multiplexed on one NPU. A single
``flm serve <chat-tag> --embed 1 --asr 1`` process serves
``/v1/chat/completions`` + ``/v1/embeddings`` + ``/v1/audio/transcriptions``
against three different models simultaneously (embed-gemma + whisper-v3
+ the chat tag). The NPU serializes execution, so multiprocess FLM
provides no parallelism gain — port the single-multiplex design from
haloai's lib/providers/flm.py.

# Hybrid container packaging:
#   - Image: hal0-toolbox-flm carries Ubuntu 24.04 + ffmpeg + libxrt-npu2
#     + libboost-program-options. Freely redistributable, ~250 MB.
#   - Host: FLM binary tree (bin/, lib/, share/, deps/) bind-mounted in
#     at the SAME absolute path inside the container so that
#     ``bin/xclbins -> /mnt/ai-models/flm-ubuntu/share/flm/xclbins``
#     (an absolute symlink) still resolves. Discovered while
#     containerising on haloai 2026-05-15.
#   - Models: FLM's own cache dir (``~/.config/flm/models/``) bind-mounted
#     to a hal0-managed dir so model downloads persist across container
#     restarts.
# See docs/handoff-2026-05-15-autonomous.md for the test that proved
# this layout (Validate / serve / embed all succeeded; chat is blocked
# only by whoever currently holds the NPU's hardware context, not by
# anything container-side).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from hal0.errors import Hal0Error
from hal0.providers.base import ContainerSpec, Provider

# ── Toolbox image ─────────────────────────────────────────────────────────────
# Default tag. Override via HAL0_TOOLBOX_IMAGE_FLM in api.env when running
# on hal0-test before the GHCR org is provisioned (PLAN §17).
_DEFAULT_FLM_IMAGE = "ghcr.io/hal0ai/hal0-toolbox-flm:v1"

# ── On-disk layout ────────────────────────────────────────────────────────────
# The toolbox image is self-contained: it bundles FLM at /opt/fastflowlm/
# (binary, libs, xclbins, share assets) and symlinks /usr/local/bin/flm
# at the binary. ENTRYPOINT runs the in-image flm via tini, so the
# container_spec only supplies the subcommand + args.
#
# _DEFAULT_FLM_ROOT below is retained ONLY for the non-container fallback
# path used by start_cmd() (native systemd runs, tests, debug shells).
# Container runs no longer reference it.
_IMAGE_FLM_ROOT = "/opt/fastflowlm"
_DEFAULT_FLM_ROOT = "/opt/hal0/flm-ubuntu"
# FLM's per-user model cache. Bind-mounted writable so `flm pull` downloads
# survive container restarts.
_DEFAULT_FLM_MODELS_DIR = "/var/lib/hal0/flm-models"

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


def _resolve_render_gid() -> int | None:
    """Look up the ``render`` group's numeric gid on the host.

    Slot containers need this group to read /dev/accel/accel0 and
    /dev/dri/renderD128. The gid varies between hosts (993 on Strix Halo
    LXCs, 109 on some bare-metal Debian, etc.) so we resolve once at
    container-spec build time rather than baking it into the image.

    Returns ``None`` if the group can't be resolved — the slot will still
    launch but device reads may fail; the slot's health probe will catch
    it.
    """
    try:
        import grp

        return grp.getgrnam("render").gr_gid
    except (KeyError, ImportError, OSError):
        return None


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

        Returned vars are stamped into the slot's EnvironmentFile so the
        rendered docker command can refer to them via ``${HAL0_*}``. Kept
        separate from container_spec so non-container callers (tests,
        debug shells, native systemd fallback) can use them too.
        """
        port = slot_cfg.get("port") or slot_cfg.get("slot", {}).get("port", 8086)
        ctx = slot_cfg.get("ctx_size") or slot_cfg.get("defaults", {}).get("context_size", 8192)
        flm_tag = model_info.get("flm_tag") or model_info.get("_model_key") or "qwen3:0.6b"

        defaults = slot_cfg.get("defaults", {})
        load_asr = "1" if defaults.get("load_asr") else "0"
        load_embed = "1" if defaults.get("load_embed") else "0"

        return {
            "HAL0_FLM_TAG": str(flm_tag),
            "HAL0_PORT": str(port),
            "HAL0_FLM_CTX": str(ctx),
            "HAL0_FLM_LOAD_ASR": load_asr,
            "HAL0_FLM_LOAD_EMBED": load_embed,
        }

    def start_cmd(self, env: dict[str, str]) -> list[str]:
        """Return argv for the native ``flm serve`` invocation.

        Used by tests and the fallback systemd-without-Docker path. The
        primary deployment path is ``container_spec``.
        """
        binary = os.environ.get("HAL0_FLM_BINARY", f"{_DEFAULT_FLM_ROOT}/bin/flm")
        argv = [
            binary,
            "serve",
            env["HAL0_FLM_TAG"],
            "--host",
            "0.0.0.0",
            "--port",
            env["HAL0_PORT"],
            "--ctx-len",
            env["HAL0_FLM_CTX"],
        ]
        if env.get("HAL0_FLM_LOAD_EMBED") == "1":
            argv += ["--embed", "1"]
        if env.get("HAL0_FLM_LOAD_ASR") == "1":
            argv += ["--asr", "1"]
        return argv

    # ── Image / container spec ─────────────────────────────────────────────────

    def image_ref(self, _slot_cfg: dict[str, Any]) -> str:
        """Return the FLM toolbox image reference.

        Allows pre-GHCR-org deploys to override via env var (matches the
        Vulkan/ROCm toolbox pattern).
        """
        return os.environ.get("HAL0_TOOLBOX_IMAGE_FLM", _DEFAULT_FLM_IMAGE)

    def container_spec(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> ContainerSpec:
        """Build a ContainerSpec for FLM in the toolbox image.

        The toolbox image is self-contained: FLM is built in and lives at
        /opt/fastflowlm/ (binary, libs, xclbins, share assets). The image
        ENTRYPOINT is ``tini -- /usr/local/bin/flm``, so the command we
        pass becomes the flm subcommand + args — no host bind-mount of
        the binary tree is needed.

        Only the model cache is bind-mounted, so ``flm pull`` downloads
        survive container restarts.

        FLM needs ``/dev/accel/accel0`` for the AMD XDNA2 NPU. ``/dev/dri``
        is included because some FLM model loaders hit iGPU helpers
        during init.
        """
        env = self.build_env(slot_cfg, model_info)
        port = int(env["HAL0_PORT"])

        paths = slot_cfg.get("_paths", {}) or {}
        flm_models = (
            paths.get("flm_models")
            or os.environ.get("HAL0_FLM_MODELS_DIR")
            or _DEFAULT_FLM_MODELS_DIR
        )

        # Only the model cache is bind-mounted. FLM hardcodes
        # ~/.config/flm/models internally; map our hal0-managed cache
        # to that path.
        mounts: list[tuple[str, str]] = [
            (flm_models, "/root/.config/flm/models"),
        ]

        # Build the argv passed to the image's ENTRYPOINT. The image runs
        # /usr/local/bin/flm via tini, so what we provide here is the
        # subcommand + flags — NOT a binary path. Passing an absolute
        # binary path here would be treated by flm as a stray positional
        # argument and rejected with "too many positional options".
        command: list[str] = [
            "serve",
            env["HAL0_FLM_TAG"],
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
            "--ctx-len",
            env["HAL0_FLM_CTX"],
        ]
        if env["HAL0_FLM_LOAD_EMBED"] == "1":
            command += ["--embed", "1"]
        if env["HAL0_FLM_LOAD_ASR"] == "1":
            command += ["--asr", "1"]

        # render group resolves dynamically at run-time; use the numeric gid
        # so the spec doesn't depend on /etc/group in the container.
        render_gid = _resolve_render_gid()

        return ContainerSpec(
            image=self.image_ref(slot_cfg),
            command=command,
            env={
                # Image-internal paths (the Dockerfile installs FLM at
                # /opt/fastflowlm and XRT at /opt/xilinx/xrt).
                "FLM_CONFIG_PATH": f"{_IMAGE_FLM_ROOT}/share/flm/model_list.json",
                # Docker `--env LD_LIBRARY_PATH=...` REPLACES the image ENV
                # set by the Dockerfile rather than augmenting it, so we
                # must spell out every path here even though the image's
                # own ENV would be correct on its own. libxrt_coreutil.so.2
                # (XRT runtime) and the FLM libs (libllama_npu.so &c, dlopen'd
                # when models load) both need to be findable; missing either
                # crashes /usr/local/bin/flm at startup before main().
                "LD_LIBRARY_PATH": f"{_IMAGE_FLM_ROOT}/lib:/opt/xilinx/xrt/lib:/usr/lib/x86_64-linux-gnu",
            },
            mounts=mounts,
            # /dev/accel/accel0: XDNA2 NPU. /dev/dri/renderD128: iGPU companion.
            devices=["/dev/accel/accel0", "/dev/dri/renderD128"],
            cap_add=[],
            # apparmor=unconfined is required in LXC; on bare metal a
            # tailored profile would be tighter but Strix Halo deployments
            # under Proxmox LXC are the primary target.
            security_opt=["apparmor=unconfined"],
            group_add=[str(render_gid)] if render_gid is not None else [],
            port=port,
            # FLM's /v1/* server needs to be reachable from the dispatcher
            # at 127.0.0.1:<port>. Use port-mapping rather than network=host
            # so multiple slots can coexist with overlapping internal ports.
            network_mode="",
            extra_args=[
                f"-p 127.0.0.1:{port}:{port}",
                # NPU model weights are pinned in DMA-locked memory; this
                # is the same flag haloai's systemd unit sets.
                "--ulimit memlock=-1",
            ],
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

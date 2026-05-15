# hal0-toolbox-moonshine — Moonshine STT (speech-to-text) server.
#
# Target image:    ghcr.io/<owner>/hal0-toolbox-moonshine:v1
# Local dev tag:   hal0-toolbox-moonshine:dev
#
# Provider contract (src/hal0/providers/moonshine.py):
#   - binary path:      /usr/local/bin/moonshine-server
#   - CLI flags:        --model_path, --model_arch, --port, --host
#   - endpoints:
#       GET  /health                  -> {status, model_loaded, model_arch}
#       GET  /v1/models               -> {data: [{id: "moonshine-<arch>-en"}]}
#       POST /v1/audio/transcriptions -> OpenAI-compat multipart upload
#       WS   /v1/audio/stream         -> live PCM16 @ 16kHz mono
#   - default arch: small_streaming (also: tiny, tiny_streaming, base, small)
#   - runtime devices:  /dev/dri (optional, Vulkan EP if iGPU present)
#
# Build:
#   docker build -t hal0-toolbox-moonshine:dev \
#       -f packaging/toolbox/moonshine.Dockerfile .
#
# Smoke test (no model loaded):
#   docker run --rm -p 8089:8089 hal0-toolbox-moonshine:dev \
#       --model_arch tiny --port 8089 --host 0.0.0.0
#   curl http://127.0.0.1:8089/health
#
# NOTE: Moonshine ships official ONNX/CT2 weights under usefulsensors/
# on HuggingFace.  The hal0 ModelRegistry resolves --model_path to a
# host path; this image only needs the *runtime* — weights live on the
# bind-mounted host filesystem.
#
# Upstream: https://github.com/usefulsensors/moonshine — Apache 2.0.
# Server wrapper authored fresh for hal0 (no upstream FastAPI shim
# exists; haloai had lib/voice/moonshine_server.py ~250 LOC but is not
# copied — this image re-implements the contract documented in the
# Provider).

FROM python:3.12-slim-bookworm AS runtime

ARG DEBIAN_FRONTEND=noninteractive

# Runtime deps:
# - ffmpeg          : transcode incoming audio (webm/m4a/...) to PCM16
# - libsndfile1     : soundfile python backend
# - mesa-vulkan-drivers + libvulkan1 : optional Vulkan ICD for ONNX-RT
#                     VulkanEP when /dev/dri is passed; harmless on CPU
# - tini            : PID 1 reaper so SIGTERM from docker stop propagates
# - curl            : healthcheck + HF model fetch fallback
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        libgomp1 \
        mesa-vulkan-drivers \
        libvulkan1 \
        tini \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Moonshine ONNX runtime + audio I/O + FastAPI host.
#   useful-moonshine-onnx — official upstream package; CPU-only
#                            (drops PyTorch).
#   onnxruntime           — CPU EP; install onnxruntime-vulkan separately
#                            if/when upstream publishes Linux wheels.
#   tokenizers            — moonshine's text decode
#   uvicorn[standard]     — websockets + httptools for /v1/audio/stream
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        useful-moonshine-onnx==20251121 \
        onnxruntime==1.20.1 \
        tokenizers \
        numpy \
        soundfile \
        fastapi==0.115.6 \
        "uvicorn[standard]==0.32.1" \
        python-multipart==0.0.20 \
        httpx

# Install the moonshine-server FastAPI app.
# The provider's start_cmd expects /usr/local/bin/moonshine-server to be
# directly executable with the CLI flags listed above.
COPY packaging/toolbox/moonshine/moonshine_server.py /opt/moonshine/moonshine_server.py
RUN printf '#!/bin/sh\nexec python3 /opt/moonshine/moonshine_server.py "$@"\n' \
        > /usr/local/bin/moonshine-server \
    && chmod 0755 /usr/local/bin/moonshine-server

# UID/GID match the host hal0 user; bind-mounted models read cleanly.
# Home dir is /var/lib/hal0 so HuggingFace cache (~/.cache/huggingface)
# resolves under a writable, hal0-owned path inside the container.
#
# We also pre-create the `render` (GID 993) and `video` (GID 44) groups
# inside the image so docker --group-add render / --group-add video
# (used by the MoonshineProvider.ContainerSpec) resolves cleanly. Docker
# looks names up against the CONTAINER's /etc/group; without these the
# slot fails with "Unable to find group render". Conventional Linux GIDs
# (993 for render, 44 for video) match host iGPU device ownership on
# the canonical hal0 deployment.
RUN groupadd --system --gid 44  video  2>/dev/null || true \
    && groupadd --system --gid 993 render 2>/dev/null || true \
    && groupadd --system --gid 1000 hal0 \
    && useradd  --system --uid 1000 --gid 1000 --shell /usr/sbin/nologin \
                --home-dir /var/lib/hal0 hal0 \
    && usermod -aG video,render hal0 \
    && mkdir -p /var/lib/hal0/models /var/lib/hal0/.cache/huggingface \
    && chown -R hal0:hal0 /var/lib/hal0 /opt/moonshine

ENV HOME=/var/lib/hal0 \
    HF_HOME=/var/lib/hal0/.cache/huggingface \
    XDG_CACHE_HOME=/var/lib/hal0/.cache

USER hal0
WORKDIR /var/lib/hal0

EXPOSE 8089

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${HAL0_PORT:-8089}/health" || exit 1

# tini -- moonshine-server <args from ContainerSpec.command[]>
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/moonshine-server"]

# Default CMD prints --help; the provider's ContainerSpec.command[]
# overrides this at runtime.
CMD ["--help"]

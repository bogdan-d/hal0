# hal0-toolbox-kokoro — Kokoro-82M TTS server (CPU ONNX).
#
# Target image:    ghcr.io/<owner>/hal0-toolbox-kokoro:v1
# Local dev tag:   hal0-toolbox-kokoro:dev
#
# Provider contract (src/hal0/providers/kokoro.py):
#   - binary path:      /usr/local/bin/kokoro-server
#   - CLI flags:        --model_path, --default_voice, --port, --host
#   - endpoints:
#       GET  /health                  -> {status: "ok", ...}
#       GET  /v1/models               -> {data: [{id: "kokoro"}]}
#       POST /v1/audio/speech         -> OpenAI-compat TTS (raw audio bytes)
#       GET  /v1/audio/voices         -> {voices: [...]}  (remsky extension)
#   - runtime devices:  none (CPU) or /dev/dri (Vulkan EP, opt-in)
#   - default voice:    af_bella
#
# Build:
#   docker build -t hal0-toolbox-kokoro:dev \
#       -f packaging/toolbox/kokoro.Dockerfile .
#
# Smoke test:
#   docker run --rm -p 8090:8090 hal0-toolbox-kokoro:dev \
#       --model_path /var/lib/hal0/models --port 8090 --host 0.0.0.0
#   curl http://127.0.0.1:8090/health
#
# Upstream weights: hexgrad/Kokoro-82M (Apache 2.0). The image downloads
# the ONNX weights on first start via kokoro-onnx auto-fetch unless a
# bind-mounted /var/lib/hal0/models/kokoro/ tree is present.
#
# NOTE: Upstream reference remsky/Kokoro-FastAPI has a richer API but
# binds 8880 and has different CLI flags. We write our own thin server
# so the Provider's contract is the ground truth.

FROM python:3.12-slim-bookworm AS runtime

ARG DEBIAN_FRONTEND=noninteractive

# Runtime:
# - espeak-ng + libespeak-ng1 : phonemizer backend Kokoro uses for G2P
# - ffmpeg                    : transcode to mp3/opus/aac on demand
# - libsndfile1               : soundfile python backend (wav/flac)
# - mesa-vulkan-drivers       : optional, for --backend vulkan
# - tini                      : PID 1
# - curl                      : healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        espeak-ng \
        libespeak-ng1 \
        ffmpeg \
        libsndfile1 \
        libgomp1 \
        mesa-vulkan-drivers \
        libvulkan1 \
        tini \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Kokoro inference (CPU ONNX) + FastAPI host.
#   kokoro-onnx     — official ONNX runtime for Kokoro-82M (pulls
#                     phonemizer-fork + espeak-ng for English G2P)
#   onnxruntime     — CPU EP
#   soundfile       — audio IO
#   fastapi/uvicorn — http surface
#
# NOTE: We intentionally omit misaki[en]; misaki transitively drags in
# spacy + torch + nvidia-cuda libs (+7GB) and is only required for
# kokoro-onnx v1.0+. The 0.4.x line phonemizes through espeak-ng via
# phonemizer-fork — installed system-wide as espeak-ng above.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        kokoro-onnx==0.4.9 \
        onnxruntime==1.20.1 \
        numpy \
        soundfile \
        fastapi==0.115.6 \
        "uvicorn[standard]==0.32.1" \
        httpx

COPY packaging/toolbox/kokoro/kokoro_server.py /opt/kokoro/kokoro_server.py
RUN printf '#!/bin/sh\nexec python3 /opt/kokoro/kokoro_server.py "$@"\n' \
        > /usr/local/bin/kokoro-server \
    && chmod 0755 /usr/local/bin/kokoro-server

# UID/GID match host hal0; bind-mounted models read cleanly.
# Home dir → /var/lib/hal0 so HF/kokoro-onnx auto-fetch can write its
# cache (~/.cache/...) on first synthesis.
#
# Pre-create `render` (GID 993) + `video` (GID 44) groups so
# docker --group-add render / video (KokoroProvider.ContainerSpec when
# backend=vulkan) resolves against /etc/group inside the container.
# See moonshine.Dockerfile for the same rationale.
RUN groupadd --system --gid 44  video  2>/dev/null || true \
    && groupadd --system --gid 993 render 2>/dev/null || true \
    && groupadd --system --gid 1000 hal0 \
    && useradd  --system --uid 1000 --gid 1000 --shell /usr/sbin/nologin \
                --home-dir /var/lib/hal0 hal0 \
    && usermod -aG video,render hal0 \
    && mkdir -p /var/lib/hal0/models /var/lib/hal0/.cache/huggingface \
    && chown -R hal0:hal0 /var/lib/hal0 /opt/kokoro

ENV HOME=/var/lib/hal0 \
    HF_HOME=/var/lib/hal0/.cache/huggingface \
    XDG_CACHE_HOME=/var/lib/hal0/.cache

USER hal0
WORKDIR /var/lib/hal0

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${HAL0_PORT:-8090}/health" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/kokoro-server"]
CMD ["--help"]

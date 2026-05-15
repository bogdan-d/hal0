# hal0-toolbox-comfyui — ComfyUI image-generation backend (ROCm / Strix Halo)
#
# Target image:    ghcr.io/hal0ai/hal0-toolbox-comfyui:v1
# Local dev tag:   hal0-toolbox-comfyui:dev
#
# Provider contract (src/hal0/providers/comfyui.py):
#   - ENTRYPOINT runs ComfyUI's `python main.py` with hal0 defaults.
#     ContainerSpec.command[] passes flags only.
#   - runtime devices:  /dev/kfd, /dev/dri (Strix Halo iGPU)
#   - runtime groups:   render, video (numeric GIDs from host)
#   - mounts:           /var/lib/hal0/comfyui ↔ /var/lib/hal0/comfyui
#                       (models/, custom_nodes/, output/, input/ persist)
#   - listen port:      8186 (slot default), 8188 (ComfyUI default)
#
# Build:
#   docker build -t hal0-toolbox-comfyui:dev -f packaging/toolbox/comfyui.Dockerfile .
#
# Verify on a Strix Halo host:
#   mkdir -p /var/lib/hal0/comfyui/models/checkpoints
#   # drop SDXL Turbo into models/checkpoints first; then:
#   docker run --rm -p 8188:8188 \
#       --device=/dev/kfd --device=/dev/dri \
#       --group-add 993 --group-add 44 \
#       -v /var/lib/hal0/comfyui:/var/lib/hal0/comfyui \
#       --security-opt=seccomp=unconfined --security-opt=apparmor=unconfined \
#       hal0-toolbox-comfyui:dev
#   curl http://127.0.0.1:8188/system_stats
#
# CI scope: the GHA matrix builds this on ubuntu-latest with no GPU. The
# ROCm wheel is fetched via pip (CPU-friendly download); the GPU code is
# only exercised at run-time on a real ROCm host. The 60-min timeout in
# .github/workflows/toolbox.yml accommodates the ~3-4 GB pip install
# (PyTorch ROCm wheel + dependencies + ComfyUI's Python deps).
#
# CUDA variant: deferred for v1. PLAN.md's primary hardware is Strix
# Halo (iGPU, ROCm-friendly). A separate `comfyui-cuda.Dockerfile` for
# discrete NVIDIA boxes is on the v0.2 backlog.

# Pin ComfyUI to a specific commit. The image-gen ecosystem moves fast
# and tracking master breaks reproducibility (cosign signs by content
# digest, but the contents change every build if upstream did). Bump
# this ARG when validating a new release.
#
# 0.3.62 is a December 2025 ComfyUI release tag.
ARG COMFYUI_REF=v0.3.62

# AMDGPU target archs for the runtime wheel-link path. Same default
# as packaging/toolbox/rocm.Dockerfile so a multi-arch build covers
# Strix Halo (gfx1151) and discrete RDNA 3 dGPUs (gfx1100).
ARG AMDGPU_TARGETS="gfx1100;gfx1151"

# ─── Stage 1 — runtime base (ROCm + Python) ───────────────────────────────────
#
# rocm/dev-ubuntu-24.04:6.4.4-complete is large (~22 GB) but pre-bundles
# every ROCm component the PyTorch ROCm wheel needs at runtime. The
# alternative (rocm-terminal) doesn't ship hipblaslt / miopen which Flux
# and SDXL both need for fused attention.
FROM rocm/dev-ubuntu-24.04:6.4.4-complete AS runtime

ARG COMFYUI_REF
ARG AMDGPU_TARGETS
ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    HSA_OVERRIDE_GFX_VERSION="" \
    AMDGPU_TARGETS="${AMDGPU_TARGETS}" \
    HAL0_PORT=8188

# System deps:
# - python3.12 + pip       : ComfyUI's runtime
# - git                    : `git clone` of ComfyUI itself + custom-node installs
# - build-essential        : custom nodes that ship C extensions sometimes need this
# - libgl1, libglib2.0-0   : OpenCV + PIL native deps
# - ffmpeg                 : video / animation custom nodes
# - curl, ca-certificates  : healthcheck + HuggingFace fetches
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 \
        python3-pip \
        python3.12-venv \
        git \
        build-essential \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        ffmpeg \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python3

# ─── Stage 2 — ComfyUI + PyTorch ROCm + deps ──────────────────────────────────
WORKDIR /app

# Clone ComfyUI at the pinned ref. shallow + branch-only to keep the
# layer tight and the cache footprint reasonable.
RUN git clone --depth 1 --branch "${COMFYUI_REF}" \
        https://github.com/comfyanonymous/ComfyUI.git . \
    || (git clone https://github.com/comfyanonymous/ComfyUI.git . \
        && git checkout "${COMFYUI_REF}")

# PyTorch ROCm wheel — pinned to the ROCm 6.2 wheel index. AMD's wheels
# are forward-compatible with newer ROCm runtimes (we ship 6.4 in the
# base image), so this gives us a stable surface even when the base
# image bumps. ROCm 6.2 wheels were the first to officially support
# RDNA 3.5 (gfx1151, Strix Halo).
#
# torch-2.4 is the validated baseline for ComfyUI 0.3.x against ROCm 6.2.
RUN pip install --index-url https://download.pytorch.org/whl/rocm6.2 \
        torch==2.4.1+rocm6.2 \
        torchvision==0.19.1+rocm6.2 \
    && pip install -r requirements.txt

# Pre-create the persistent layout so the bind-mounted host directory
# starts with the right shape even on first run.
RUN mkdir -p \
        /var/lib/hal0/comfyui/models/checkpoints \
        /var/lib/hal0/comfyui/models/loras \
        /var/lib/hal0/comfyui/models/vae \
        /var/lib/hal0/comfyui/models/clip \
        /var/lib/hal0/comfyui/models/embeddings \
        /var/lib/hal0/comfyui/models/upscale_models \
        /var/lib/hal0/comfyui/custom_nodes \
        /var/lib/hal0/comfyui/output \
        /var/lib/hal0/comfyui/input

# Default cmd — ContainerSpec overrides --listen / --port / --base-directory
# at runtime. This default is what gets hit during a `docker run` smoke
# test with no flags.
EXPOSE 8188

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${HAL0_PORT:-8188}/system_stats" || exit 1

# ENTRYPOINT runs python main.py so ContainerSpec.command[] starts with
# "python main.py ..." and gets passed straight through. We keep the
# entrypoint a bash -c so $HAL0_PORT (set by the slot's EnvironmentFile)
# can be used in the default cmd; ContainerSpec overrides this anyway.
WORKDIR /app
ENTRYPOINT ["python", "main.py"]
CMD ["--listen", "0.0.0.0", "--port", "8188", "--base-directory", "/var/lib/hal0/comfyui"]

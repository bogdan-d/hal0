# hal0-toolbox-rocm — llama.cpp ROCm (HIP) backend for discrete AMD GPUs.
#
# Target image:    ghcr.io/<owner>/hal0-toolbox-rocm:v1
# Local dev tag:   hal0-toolbox-rocm:dev
#
# Provider contract (src/hal0/providers/llama_server.py):
#   - ENTRYPOINT MUST be llama-server itself; ContainerSpec.command[] is
#     ARGS ONLY.
#   - runtime devices:  /dev/kfd, /dev/dri/renderD128 (host dGPU)
#   - runtime groups:   video, render (added by ContainerSpec.group_add)
#   - The contract is identical to the Vulkan image — only the build
#     toolchain (HIP) and runtime libs (ROCm) differ. Slot config selects
#     this image via slot.backend = "rocm".
#
# Build:
#   docker build -t hal0-toolbox-rocm:dev -f packaging/toolbox/rocm.Dockerfile .
#
# Verify on a ROCm host:
#   docker run --rm --device=/dev/kfd --device=/dev/dri \
#       --group-add video --group-add render \
#       hal0-toolbox-rocm:dev --help | head
#
# NOTE: The image is intentionally LARGE (~6 GB) because ROCm runtime
# libs are bundled. Vulkan image is the right default for Strix Halo
# iGPU; this image targets the dGPU upgrade path (PLAN.md §1 hardware
# class).

# ─── Stage 1 — builder (HIP toolchain) ────────────────────────────────────────
#
# ROCm publishes a complete dev image with hipcc + libraries pre-installed.
# We pin to a specific minor so build reproducibility doesn't drift on
# upstream rebuilds. 6.4 is the current supported series for Strix Halo
# dGPU companions (RX 7000) and Vega/RDNA1+.
FROM rocm/dev-ubuntu-24.04:6.4.4-complete AS builder

ARG LLAMA_CPP_REF=master
ARG DEBIAN_FRONTEND=noninteractive

# AMDGPU_TARGETS controls which GFX archs hip-clang emits code for.
# Default arch list — pruned to the two hal0 priority targets so the CI
# build fits inside the 45-90 min GHA window (full 5-arch list takes
# ~5+ hours of HIP template compilation). Operators on other archs
# (gfx1030 / gfx1101 / gfx1102) can rebuild locally with
#   docker build --build-arg AMDGPU_TARGETS=gfx1101 ...
#   gfx1100 = Radeon RX 7900 XTX/XT (RDNA 3, discrete) — fastest path
#   gfx1151 = Strix Halo iGPU (RDNA 3.5, the first-class home target)
ARG AMDGPU_TARGETS="gfx1100;gfx1151"

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        ninja-build \
        git \
        ca-certificates \
        pkg-config \
        libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --depth 1 --branch "${LLAMA_CPP_REF}" \
        https://github.com/ggml-org/llama.cpp.git . \
    || (git clone https://github.com/ggml-org/llama.cpp.git . \
        && git checkout "${LLAMA_CPP_REF}")

# Build llama.cpp with ROCm/HIP.
#   GGML_HIP=ON          : the new HIP backend name (replaced GGML_HIPBLAS)
#   AMDGPU_TARGETS=...   : multi-arch fat binary (see ARG above)
#   CMAKE_C/CXX_COMPILER : hipcc front-end for kernel code
#   BUILD_SHARED_LIBS=OFF: static-link ggml so we don't drag .so's into
#                          the runtime stage beyond ROCm's own.
RUN cmake -S . -B build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_C_COMPILER=/opt/rocm/llvm/bin/clang \
        -DCMAKE_CXX_COMPILER=/opt/rocm/llvm/bin/clang++ \
        -DGGML_HIP=ON \
        -DAMDGPU_TARGETS="${AMDGPU_TARGETS}" \
        -DLLAMA_CURL=ON \
        -DBUILD_SHARED_LIBS=OFF \
        -DLLAMA_BUILD_TESTS=OFF \
        -DLLAMA_BUILD_EXAMPLES=ON \
        -DLLAMA_BUILD_SERVER=ON \
    && cmake --build build --config Release --target llama-server -j"$(nproc)"

RUN mkdir -p /out/opt/llama-rocm/bin /out/opt/llama-rocm/lib \
    && cp build/bin/llama-server /out/opt/llama-rocm/llama-server \
    && (find build -name '*.so*' -exec cp -av {} /out/opt/llama-rocm/lib/ \; || true) \
    && strip /out/opt/llama-rocm/llama-server || true

# ─── Stage 2 — runtime (ROCm 6.2 runtime libs only) ───────────────────────────
#
# rocm/dev:*-complete is ~22 GB; the rocm/rocm-terminal:* is the
# slimmer "runtime + minimum tooling" variant and pulls in just the
# libraries llama-server needs (hipblas/rocblas/rocrand/hsa-runtime).
FROM rocm/rocm-terminal:6.4 AS runtime

ARG DEBIAN_FRONTEND=noninteractive
USER root

# Runtime: curl for --hf-repo; vulkan-tools is intentionally NOT
# installed — this image is ROCm-only.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libcurl4 \
        libstdc++6 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

COPY --from=builder /out/opt/llama-rocm /opt/llama-rocm

# ROCm libraries live under /opt/rocm/lib; the llama-server binary
# was linked against them. /opt/llama-rocm/lib only has shared ggml
# fragments produced by the build (if any).
ENV LD_LIBRARY_PATH=/opt/llama-rocm/lib:/opt/rocm/lib \
    PATH=/opt/llama-rocm:/opt/rocm/bin:${PATH} \
    HSA_OVERRIDE_GFX_VERSION="" \
    HCC_AMDGPU_TARGET=""

# Match the same UID:GID convention the Vulkan image uses so bind-mounts
# from the host hal0 user (1000:1000) land correctly. rocm-terminal
# ships with a `rocm-user` at UID 1000 we replace.
#
# Pre-create render (GID 993) + video (GID 44) groups so docker
# --group-add resolves names through the container's /etc/group; the
# ContainerSpec passes ["video", "render"] as names, not numeric GIDs.
RUN userdel --remove rocm-user 2>/dev/null || true \
    && groupadd --system --gid 44  video  2>/dev/null || true \
    && groupadd --system --gid 993 render 2>/dev/null || true \
    && groupadd --system --gid 1000 hal0 2>/dev/null || true \
    && useradd  --system --uid 1000 --gid 1000 --shell /usr/sbin/nologin hal0 \
    && usermod -aG video,render hal0

RUN mkdir -p /var/lib/hal0/models && chown -R hal0:hal0 /var/lib/hal0

USER hal0
WORKDIR /var/lib/hal0

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${HAL0_PORT:-8081}/v1/models" || exit 1

ENTRYPOINT ["/opt/llama-rocm/llama-server"]
CMD ["--help"]

# hal0-toolbox-flm — FastFlowLM (FLM) on AMD Strix Halo XDNA2 NPU.
#
# Target image:    ghcr.io/<owner>/hal0-toolbox-flm:v1
# Local dev tag:   hal0-toolbox-flm:dev
#
# Provider contract (src/hal0/providers/flm.py):
#   - binary path:      /usr/local/bin/flm
#   - subcommand:       `flm serve <model_tag> --port N --host 0.0.0.0 --ctx-len C`
#   - endpoints:        /v1/models, /v1/chat/completions, /v1/embeddings,
#                       /v1/audio/transcriptions (when --asr is enabled)
#   - runtime devices:  /dev/accel (XDNA2 NPU), /dev/dri (iGPU helpers)
#   - runtime ulimits:  --ulimit memlock=-1:-1 (NPU buffer pinning)
#   - model cache:      /root/.config/flm (bind-mount via slot_cfg._paths.flm_cache)
#
# Upstream: https://github.com/FastFlowLM/FastFlowLM — Apache 2.0
# Driver:   https://github.com/amd/xdna-driver (XRT + xdna NPU plugin)
# Reference: https://github.com/hpenedones/fastflowlm-docker (3-stage build,
#            ~440MB final, ~15-25 min build time on a fast box).
#
# HOST REQUIREMENTS (cannot be satisfied inside the image):
#   - Linux kernel ≥ 6.11 with `amdxdna` loaded
#   - NPU firmware ≥ 1.1.0.0
#   - /dev/accel/accel0 visible on the host
#
# Build:
#   docker build -t hal0-toolbox-flm:dev -f packaging/toolbox/flm.Dockerfile .
#
# Smoke (on a Strix Halo host with NPU passthrough):
#   docker run --rm --device=/dev/accel --device=/dev/dri \
#       --ulimit memlock=-1:-1 --group-add video --group-add render \
#       hal0-toolbox-flm:dev flm validate
#
# NOTE: This Dockerfile builds FLM + XRT from source. Build hosts WITHOUT
# the xdna driver kernel headers will still compile cleanly — the
# xdna-driver userspace bits are headers + libraries, not kernel modules.
# Only RUNTIME requires the host kernel + /dev/accel.

# ─── Stage 1 — XRT + xdna-driver userspace builder ────────────────────────────
FROM ubuntu:24.04 AS xrt-builder

ARG DEBIAN_FRONTEND=noninteractive
ARG XDNA_REF=main

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        git \
        ca-certificates \
        libboost-dev \
        libboost-program-options-dev \
        libdrm-dev \
        libelf-dev \
        libssl-dev \
        libudev-dev \
        ocl-icd-dev \
        pkg-config \
        protobuf-compiler \
        python3 \
        python3-pip \
        pybind11-dev \
        rapidjson-dev \
        uuid-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --recurse-submodules \
        https://github.com/amd/xdna-driver.git . \
    && git checkout "${XDNA_REF}" \
    && git submodule update --init --recursive

# xdna-driver bundles upstream XRT as a submodule under xrt/.
# Build XRT first, then the xdna plugin against it. The Makefile-based
# top-level build script knows the right order.
RUN cd xrt/build && ./build.sh -opt && ./build.sh -install

# Build the xdna NPU plugin against the XRT we just installed.
RUN mkdir -p build && cd build \
    && cmake -DCMAKE_INSTALL_PREFIX=/opt/xilinx/xrt .. \
    && make -j"$(nproc)" \
    && make install

# ─── Stage 2 — FLM builder ────────────────────────────────────────────────────
FROM ubuntu:24.04 AS flm-builder

ARG DEBIAN_FRONTEND=noninteractive
ARG FLM_REF=main

# Pull the freshly-built XRT in so FLM can link against it.
COPY --from=xrt-builder /opt/xilinx/xrt /opt/xilinx/xrt

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        ninja-build \
        git \
        ca-certificates \
        libboost-program-options-dev \
        libcurl4-openssl-dev \
        libfftw3-dev \
        libavformat-dev \
        libavcodec-dev \
        libswscale-dev \
        libreadline-dev \
        libdrm-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --recurse-submodules \
        https://github.com/FastFlowLM/FastFlowLM.git . \
    && git checkout "${FLM_REF}" \
    && git submodule update --init --recursive

# FLM ships a CMake preset that points at /opt/xilinx/xrt.
RUN cmake --preset linux-default \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/fastflowlm \
        -DXRT_INCLUDE_DIR=/opt/xilinx/xrt/include \
        -DXRT_LIB_DIR=/opt/xilinx/xrt/lib \
    && cmake --build build -j"$(nproc)" \
    && cmake --install build

# ─── Stage 3 — runtime ────────────────────────────────────────────────────────
FROM ubuntu:24.04 AS runtime

ARG DEBIAN_FRONTEND=noninteractive

# Runtime deps only — no compilers, headers, or source.
# Boost-program-options, FFTW, ffmpeg-libs, readline are FLM's runtime
# link-time deps; libdrm/libelf/libudev are XRT's; curl/ca-certificates
# for FLM's model pull from HF.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libboost-program-options1.83.0 \
        libcurl4 \
        libfftw3-single3 \
        libavformat60 \
        libavcodec60 \
        libswscale7 \
        libreadline8t64 \
        libdrm2 \
        libelf1t64 \
        libudev1 \
        libgomp1 \
        ca-certificates \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Copy XRT runtime libs + xdna plugin.
COPY --from=xrt-builder /opt/xilinx/xrt/lib /opt/xilinx/xrt/lib
COPY --from=xrt-builder /opt/xilinx/xrt/bin /opt/xilinx/xrt/bin
COPY --from=xrt-builder /opt/xilinx/xrt/share /opt/xilinx/xrt/share

# Copy FLM tree (binary + xclbins + share assets).
COPY --from=flm-builder /opt/fastflowlm /opt/fastflowlm

# Symlink the binary so the Provider's start_cmd default (/usr/local/bin/flm)
# resolves. The Provider also accepts HAL0_FLM_BINARY override.
RUN ln -sf /opt/fastflowlm/bin/flm /usr/local/bin/flm

ENV LD_LIBRARY_PATH=/opt/xilinx/xrt/lib:/opt/fastflowlm/lib \
    PATH=/opt/xilinx/xrt/bin:/opt/fastflowlm/bin:${PATH} \
    FLM_XCLBIN_PATH=/opt/fastflowlm/share/flm/xclbins

# UID/GID match host hal0; bind-mounted model cache reads cleanly.
# NOTE: FLM defaults its model cache to ~/.config/flm; the slot's
# ContainerSpec bind-mounts host flm_cache into the same in-container
# path (see flm.py:container_spec).
#
# Pre-create render/video groups so docker --group-add (FLM ContainerSpec
# passes ["video", "render"]) resolves inside the container.
RUN groupadd --system --gid 44  video  2>/dev/null || true \
    && groupadd --system --gid 993 render 2>/dev/null || true \
    && groupadd --system --gid 1000 hal0 \
    && useradd  --system --uid 1000 --gid 1000 --shell /usr/sbin/nologin \
                --home-dir /var/lib/hal0 --create-home hal0 \
    && usermod -aG video,render hal0 \
    && mkdir -p /var/lib/hal0/.config/flm /var/lib/hal0/models \
    && chown -R hal0:hal0 /var/lib/hal0

USER hal0
WORKDIR /var/lib/hal0

EXPOSE 8086

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${HAL0_PORT:-8086}/v1/models" || exit 1

# tini → flm. ContainerSpec.command[] supplies ["serve", <tag>, "--port", ...].
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/flm"]
CMD ["--help"]

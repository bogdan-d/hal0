#!/usr/bin/env bash
# hal0 installer — non-interactive, idempotent
#
# Usage:
#   sudo bash install.sh           # standard FHS install
#   bash install.sh --dev          # local dev layout under $PWD/hal0-home
#
# Override defaults via env vars before running:
#   HAL0_CHANNEL=stable|nightly
#   HAL0_AUTO_PULL=1|0             # pull toolbox + OpenWebUI images (Phase 2)
#   HAL0_INSTALL_DIR               # override /usr/lib/hal0
#   HAL0_PORT                      # override 8080
#   HAL0_OPENWEBUI_PORT            # override 3001

set -euo pipefail
IFS=$'\n\t'

# ── Colour helpers ────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
    BOLD='\033[1m'; RESET='\033[0m'
else
    RED=''; YELLOW=''; GREEN=''; BOLD=''; RESET=''
fi

info()  { printf "${GREEN}✔${RESET}  %s\n" "$*"; }
warn()  { printf "${YELLOW}!${RESET}  %s\n" "$*" >&2; }
error() { printf "${RED}✗${RESET}  %s\n" "$*" >&2; }
step()  { printf "\n${BOLD}── %s${RESET}\n" "$*"; }
die()   { error "$*"; exit 1; }

# ── Parse flags ───────────────────────────────────────────────────────────────
DEV_MODE=0
for arg in "$@"; do
    case "$arg" in
        --dev) DEV_MODE=1 ;;
        --help|-h)
            printf 'Usage: install.sh [--dev]\n'
            # shellcheck disable=SC2016
            printf '  --dev   install under %s/hal0-home instead of FHS paths\n' '$PWD'
            exit 0
            ;;
        *) warn "Unknown flag: $arg (ignored)" ;;
    esac
done

# ── Defaults (env-overridable) ─────────────────────────────────────────────────
HAL0_CHANNEL="${HAL0_CHANNEL:-stable}"
HAL0_AUTO_PULL="${HAL0_AUTO_PULL:-0}"
HAL0_PORT="${HAL0_PORT:-8080}"
HAL0_OPENWEBUI_PORT="${HAL0_OPENWEBUI_PORT:-3001}"
HAL0_VERSION="0.0.0-dev"

# Dev-mode overrides all FHS paths to $PWD/hal0-home
if [[ "${DEV_MODE}" -eq 1 ]]; then
    HAL0_HOME="${HAL0_HOME:-${PWD}/hal0-home}"
    HAL0_INSTALL_DIR="${HAL0_INSTALL_DIR:-${HAL0_HOME}/usr/lib/hal0}"
    ETC_DIR="${HAL0_HOME}/etc/hal0"
    VAR_DIR="${HAL0_HOME}/var/lib/hal0"
    UNIT_DIR="${HAL0_HOME}/etc/systemd/system"
    warn "Dev mode — all paths under ${HAL0_HOME}"
    warn "  systemd units written to ${UNIT_DIR} (not installed or enabled)"
else
    HAL0_INSTALL_DIR="${HAL0_INSTALL_DIR:-/usr/lib/hal0}"
    ETC_DIR="/etc/hal0"
    VAR_DIR="/var/lib/hal0"
    UNIT_DIR="/etc/systemd/system"
fi

VERSIONED_DIR="${HAL0_INSTALL_DIR}/${HAL0_VERSION}"
CURRENT_LINK="${HAL0_INSTALL_DIR}/current"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── Error trap ────────────────────────────────────────────────────────────────
trap 'error "Install failed at line ${LINENO}. Check the output above for details."; exit 1' ERR

# ── Pre-flight checks ─────────────────────────────────────────────────────────
step "Pre-flight checks"

# uid / sudo
if [[ "${DEV_MODE}" -eq 0 ]]; then
    if [[ "$(id -u)" -ne 0 ]]; then
        if command -v sudo &>/dev/null; then
            warn "Not running as root — re-exec under sudo"
            exec sudo bash "$0" "$@"
        else
            die "pre-flight failed: must run as root or have sudo available.\n       Run: sudo bash install.sh"
        fi
    fi
    info "Running as root"
else
    info "Dev mode — skipping root check"
fi

# systemd
if ! command -v systemctl &>/dev/null || ! systemctl --version &>/dev/null 2>&1; then
    die "pre-flight failed: systemd not found.\n       hal0 requires systemd. Install on Debian/Ubuntu:\n         apt install systemd"
fi
info "systemd present: $(systemctl --version | head -1)"

# architecture
ARCH="$(uname -m)"
if [[ "${ARCH}" != "x86_64" ]]; then
    die "pre-flight failed: hal0 v1 requires x86_64, got ${ARCH}.\n       ARM and other arches are planned for a future release."
fi
info "Architecture: ${ARCH}"

# Docker
if ! command -v docker &>/dev/null; then
    die "pre-flight failed: docker not installed.\n       Install via: curl -fsSL https://get.docker.com | sh\n       Then add your user to the docker group: usermod -aG docker \$USER"
fi
if ! docker info &>/dev/null 2>&1; then
    die "pre-flight failed: docker daemon not running or not accessible.\n       Start it: systemctl start docker\n       Or add your user to the docker group and re-login:\n         usermod -aG docker \$USER && newgrp docker"
fi
DOCKER_VER="$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 'unknown')"
info "Docker: ${DOCKER_VER}"

# Disk space (≥20GB free in /var/lib — or $VAR_DIR parent in dev mode)
CHECK_DIR="/var/lib"
[[ "${DEV_MODE}" -eq 1 ]] && CHECK_DIR="${PWD}"
AVAIL_KB="$(df -k "${CHECK_DIR}" | awk 'NR==2{print $4}')"
REQUIRED_KB=$((20 * 1024 * 1024))  # 20 GB
if [[ "${AVAIL_KB}" -lt "${REQUIRED_KB}" ]]; then
    AVAIL_GB=$(( AVAIL_KB / 1024 / 1024 ))
    die "pre-flight failed: less than 20GB free in ${CHECK_DIR} (have ~${AVAIL_GB}GB).\n       Free up space or set a custom model dir via a symlink:\n         ln -s /mnt/large-disk/hal0-models /var/lib/hal0/models"
fi
AVAIL_GB=$(( AVAIL_KB / 1024 / 1024 ))
info "Disk space: ~${AVAIL_GB}GB free in ${CHECK_DIR}"

# Port availability (skip in dev mode — ports not bound by systemd)
if [[ "${DEV_MODE}" -eq 0 ]]; then
    for PORT in "${HAL0_PORT}" "${HAL0_OPENWEBUI_PORT}"; do
        if ss -tlnp 2>/dev/null | grep -q ":${PORT} " || \
           netstat -tlnp 2>/dev/null | grep -q ":${PORT} "; then
            die "pre-flight failed: port ${PORT} is already in use.\n       Find the process: lsof -i :${PORT}\n       Set a different port: HAL0_PORT=8090 bash install.sh\n         (and update /etc/hal0/api.env + openwebui.env after install)"
        fi
    done
    info "Ports ${HAL0_PORT} and ${HAL0_OPENWEBUI_PORT} are free"
fi

# ── System user ───────────────────────────────────────────────────────────────
step "System user"

if [[ "${DEV_MODE}" -eq 0 ]]; then
    if ! id hal0 &>/dev/null 2>&1; then
        useradd --system --no-create-home --shell /usr/sbin/nologin \
            --comment "hal0 inference daemon" hal0
        info "Created system user: hal0"
    else
        info "System user hal0 already exists"
    fi
fi

# ── Filesystem layout ─────────────────────────────────────────────────────────
step "Filesystem layout"

mkdir -p \
    "${VERSIONED_DIR}/bin" \
    "${VERSIONED_DIR}/site-packages" \
    "${VERSIONED_DIR}/ui" \
    "${ETC_DIR}/slots" \
    "${VAR_DIR}/models" \
    "${VAR_DIR}/registry" \
    "${VAR_DIR}/openwebui" \
    "${VAR_DIR}/slots" \
    "${VAR_DIR}/cache"

# Per-slot working dirs for the four default slots
for SLOT in primary embed stt tts; do
    mkdir -p "${VAR_DIR}/slots/${SLOT}"
done

if [[ "${DEV_MODE}" -eq 0 ]]; then
    # Ownership: hal0 owns its runtime dirs; root owns code + config
    chown -R hal0:hal0 "${VAR_DIR}" || true
    chown -R root:root "${HAL0_INSTALL_DIR}" || true
    # Config: readable by hal0 so the daemon can read its own config
    chown -R root:hal0 "${ETC_DIR}" || true
    chmod -R 750 "${ETC_DIR}" || true
fi
info "Directories created"

# ── Symlink current version ───────────────────────────────────────────────────
step "Installing hal0 ${HAL0_VERSION}"

# Copy repo sources into the versioned dir
# Phase 0: copy src/hal0 + ui/dist (if it exists) + installer/bin
if [[ -d "${REPO_ROOT}/src/hal0" ]]; then
    cp -r "${REPO_ROOT}/src/hal0" "${VERSIONED_DIR}/site-packages/"
    info "Installed Python package"
else
    warn "src/hal0 not found — skipping package copy (Phase 0 scaffold only)"
fi

if [[ -d "${REPO_ROOT}/ui/dist" ]]; then
    cp -r "${REPO_ROOT}/ui/dist/." "${VERSIONED_DIR}/ui/"
    info "Installed UI dist"
else
    warn "ui/dist not found — skipping UI copy (run 'cd ui && npm run build' first)"
fi

# Install launcher scripts from installer/bin/
if [[ -d "${REPO_ROOT}/installer/bin" ]]; then
    cp "${REPO_ROOT}/installer/bin/"* "${VERSIONED_DIR}/bin/"
    chmod +x "${VERSIONED_DIR}/bin/"*
    info "Installed launcher scripts"
fi

# Create stub hal0 binary if none was built yet
if [[ ! -f "${VERSIONED_DIR}/bin/hal0" ]]; then
    cat > "${VERSIONED_DIR}/bin/hal0" <<'STUBEOF'
#!/usr/bin/env bash
# hal0 CLI stub — replace with real binary in Phase 1
echo "hal0 ${1:-help} — not yet implemented (Phase 0 scaffold)" >&2
case "${1:-}" in
    serve)
        echo "hal0 serve: listening on port ${HAL0_PORT:-8080} (stub)" >&2
        # Keep running so systemd sees a live process during dev
        exec sleep infinity
        ;;
    *) exit 1 ;;
esac
STUBEOF
    chmod +x "${VERSIONED_DIR}/bin/hal0"
    warn "Created hal0 stub binary — replace with real build in Phase 1"
fi

# Atomic symlink swap: new -> ln -sfn target link
ln -sfn "${VERSIONED_DIR}" "${CURRENT_LINK}"
info "Symlink: ${CURRENT_LINK} -> ${VERSIONED_DIR}"

# ── Config defaults ───────────────────────────────────────────────────────────
step "Default configuration"

# hal0.toml — never clobber if it already exists
if [[ ! -f "${ETC_DIR}/hal0.toml" ]]; then
    cat > "${ETC_DIR}/hal0.toml" <<TOMLEOF
# hal0 main configuration
# Edit with: hal0 config edit
# Validate with: hal0 config validate
# Migrate schema: hal0 config migrate

[meta]
schema_version = 1

[api]
port = ${HAL0_PORT}
host = "0.0.0.0"
log_level = "info"

[dispatcher]
prefetch_timeout_s = 8
per_upstream_parallel_cap = 4

[update]
channel = "${HAL0_CHANNEL}"
auto_check = true
TOMLEOF
    info "Created /etc/hal0/hal0.toml"
else
    info "hal0.toml already exists — not clobbered"
fi

# api.env
if [[ ! -f "${ETC_DIR}/api.env" ]]; then
    cat > "${ETC_DIR}/api.env" <<ENVEOF
HAL0_PORT=${HAL0_PORT}
HAL0_LOG_LEVEL=info
# Uncomment to enable telemetry (off by default)
# HAL0_TELEMETRY=1
ENVEOF
    info "Created ${ETC_DIR}/api.env"
else
    info "api.env already exists — not clobbered"
fi

# openwebui.env
if [[ ! -f "${ETC_DIR}/openwebui.env" ]]; then
    cat > "${ETC_DIR}/openwebui.env" <<ENVEOF
OPENAI_API_BASE_URLS=http://127.0.0.1:${HAL0_PORT}/v1
WEBUI_AUTH=False
WEBUI_NAME=hal0
ENABLE_OPENAI_API=True
ENABLE_OLLAMA_API=False
DATA_DIR=/app/backend/data
DEFAULT_LOCALE=en
ENVEOF
    info "Created ${ETC_DIR}/openwebui.env"
else
    info "openwebui.env already exists — not clobbered"
fi

# Default slot TOMLs — skeletons, filled by hal0 probe in Phase 2
declare -A SLOT_COMMENTS=(
    [primary]="Primary chat/completion slot (llama.cpp backend)"
    [embed]="Embedding slot (llama.cpp backend)"
    [stt]="Speech-to-text slot (Moonshine backend)"
    [tts]="Text-to-speech slot (Kokoro backend)"
)
declare -A SLOT_BACKENDS=(
    [primary]="llama_server"
    [embed]="llama_server"
    [stt]="moonshine"
    [tts]="kokoro"
)

for SLOT in primary embed stt tts; do
    SLOT_TOML="${ETC_DIR}/slots/${SLOT}.toml"
    if [[ ! -f "${SLOT_TOML}" ]]; then
        cat > "${SLOT_TOML}" <<SLOTEOF
# hal0 slot config: ${SLOT}
# ${SLOT_COMMENTS[${SLOT}]}
# Filled by: hal0 probe (Phase 2 — run after install to detect hardware)
# Edit with: hal0 config edit (or \$EDITOR ${SLOT_TOML})

[slot]
name = "${SLOT}"
backend = "${SLOT_BACKENDS[${SLOT}]}"
# model = "unset"   # set via FirstRun wizard or: hal0 model assign <ref> --slot ${SLOT}
# port = 0          # assigned automatically by hal0 (8081-8099 range)
# gpu_layers = -1   # -1 = auto (all layers to GPU)
# ctx_size = 4096
# parallel = 4
SLOTEOF
        info "Created ${ETC_DIR}/slots/${SLOT}.toml"
    else
        info "slots/${SLOT}.toml already exists — not clobbered"
    fi
done

# ── Systemd units ─────────────────────────────────────────────────────────────
step "Systemd units"

if [[ "${DEV_MODE}" -eq 0 ]]; then
    # Install units
    for UNIT in hal0-api.service hal0-openwebui.service "hal0-slot@.service"; do
        SRC="${REPO_ROOT}/installer/systemd/${UNIT}"
        DST="${UNIT_DIR}/${UNIT}"
        if [[ ! -f "${SRC}" ]]; then
            die "Unit file not found: ${SRC}\n       Run install.sh from the hal0 repo root."
        fi
        cp "${SRC}" "${DST}"
        info "Installed ${UNIT}"
    done

    systemctl daemon-reload
    info "systemctl daemon-reload done"

    systemctl enable --now hal0-api hal0-openwebui
    info "hal0-api and hal0-openwebui enabled and started"
else
    # Dev mode: write units to HAL0_HOME but don't install or enable
    mkdir -p "${UNIT_DIR}"
    for UNIT in hal0-api.service hal0-openwebui.service "hal0-slot@.service"; do
        SRC="${REPO_ROOT}/installer/systemd/${UNIT}"
        DST="${UNIT_DIR}/${UNIT}"
        if [[ -f "${SRC}" ]]; then
            cp "${SRC}" "${DST}"
            info "Wrote ${DST} (not installed — dev mode)"
        fi
    done
fi

# ── Phase 2 stubs ─────────────────────────────────────────────────────────────
step "Deferred steps"
warn "TODO: pull toolbox images (Phase 2):"
warn "  docker pull ghcr.io/hal0-dev/hal0-toolbox-vulkan:v1"
warn "  docker pull ghcr.io/hal0-dev/hal0-toolbox-rocm:v1"
warn "  docker pull ghcr.io/hal0-dev/hal0-toolbox-flm:v1"
warn "  docker pull ghcr.io/hal0-dev/hal0-toolbox-moonshine:v1"
warn "  docker pull ghcr.io/hal0-dev/hal0-toolbox-kokoro:v1"
warn "TODO: run hal0 probe (Phase 2) — hardware detect + slot defaults"

# ── Done ──────────────────────────────────────────────────────────────────────
printf '\n%s%shal0 installed successfully!%s\n\n' "${GREEN}" "${BOLD}" "${RESET}"

if [[ "${DEV_MODE}" -eq 1 ]]; then
    printf '  Layout root:  %s%s%s\n' "${BOLD}" "${HAL0_HOME}" "${RESET}"
    printf '  Config:       %s%s%s\n' "${BOLD}" "${ETC_DIR}" "${RESET}"
    printf '  Data:         %s%s%s\n' "${BOLD}" "${VAR_DIR}" "${RESET}"
    printf '\n  systemd units were NOT installed (dev mode).\n'
    printf '  To start services manually, run: bash scripts/dev-bootstrap.sh\n\n'
else
    HOST="$(hostname -I | awk '{print $1}' 2>/dev/null || echo 'localhost')"
    printf '  Dashboard:    %shttp://%s:%s%s\n' "${BOLD}" "${HOST}" "${HAL0_PORT}" "${RESET}"
    printf '  OpenWebUI:    %shttp://%s:%s%s\n' "${BOLD}" "${HOST}" "${HAL0_OPENWEBUI_PORT}" "${RESET}"
    printf '\n  Next steps:\n'
    printf '  1. Open the dashboard and complete the FirstRun wizard\n'
    printf '  2. Pick a model -- it will be downloaded and assigned to the primary slot\n'
    printf '  3. Click "Open Chat" to start chatting in OpenWebUI\n'
    printf '\n  Logs:  journalctl -fu hal0-api\n'
    printf '  Units: systemctl status hal0-api hal0-openwebui\n\n'
fi

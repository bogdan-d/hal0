#!/usr/bin/env bash
# hal0 installer — idempotent, non-interactive.
#
# Usage:
#   sudo bash install.sh             # standard install at /opt/hal0
#   bash install.sh --dev            # local-only install under $PWD/.hal0-dev
#   sudo bash install.sh --no-start  # set up everything but don't start units
#
# Env overrides:
#   HAL0_PREFIX        installation root (default /opt/hal0)
#   HAL0_PORT          API port (default 8080)
#   HAL0_USER          system user (default root — slot template uses root
#                      because the container is the real sandbox boundary)
#   HAL0_PYTHON        python interpreter (default python3)
#   HAL0_NO_PROBE=1    skip the hardware probe at the end
#   HAL0_TOOLBOX_IMAGE_VULKAN, HAL0_TOOLBOX_IMAGE_ROCM, ...
#                      override per-backend container image refs

set -euo pipefail
IFS=$'\n\t'

if [[ -t 1 ]]; then
    RED=$'\033[0;31m'; YEL=$'\033[1;33m'; GRN=$'\033[0;32m'; BLU=$'\033[0;36m'
    BOLD=$'\033[1m';   DIM=$'\033[2m';    RST=$'\033[0m'
else
    RED=; YEL=; GRN=; BLU=; BOLD=; DIM=; RST=
fi
info()  { printf "${GRN}✔${RST}  %s\n" "$*"; }
warn()  { printf "${YEL}!${RST}  %s\n" "$*" >&2; }
err()   { printf "${RED}✗${RST}  %s\n" "$*" >&2; }
step()  { printf "\n${BOLD}── %s${RST}\n" "$*"; }
die()   { err "$*"; exit 1; }

DEV_MODE=0
NO_START=0
for arg in "$@"; do
    case "$arg" in
        --dev) DEV_MODE=1 ;;
        --no-start) NO_START=1 ;;
        --help|-h)
            cat <<EOF
Usage: install.sh [--dev] [--no-start]
  --dev        install under \$PWD/.hal0-dev/, no systemd setup
  --no-start   set up everything but don't enable/start the API
EOF
            exit 0
            ;;
        *) warn "unknown flag: ${arg} (ignored)" ;;
    esac
done

HAL0_PORT="${HAL0_PORT:-8080}"
HAL0_USER="${HAL0_USER:-root}"
PY="${HAL0_PYTHON:-python3}"

if [[ "${DEV_MODE}" -eq 1 ]]; then
    PREFIX="${HAL0_PREFIX:-${PWD}/.hal0-dev}"
    ETC_DIR="${PREFIX}/etc/hal0"
    VAR_DIR="${PREFIX}/var/lib/hal0"
    UNIT_DIR="${PREFIX}/etc/systemd/system"
    info "Dev mode — all paths under ${PREFIX}"
else
    PREFIX="${HAL0_PREFIX:-/opt/hal0}"
    ETC_DIR="/etc/hal0"
    VAR_DIR="/var/lib/hal0"
    UNIT_DIR="/etc/systemd/system"
fi
VENV_DIR="${PREFIX}/.venv"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

trap 'err "install failed at line ${LINENO}. See output above."; exit 1' ERR

step "Pre-flight checks"

if [[ "${DEV_MODE}" -eq 0 && "$(id -u)" -ne 0 ]]; then
    if command -v sudo >/dev/null; then
        warn "Re-exec under sudo"
        exec sudo -E HAL0_PORT="${HAL0_PORT}" HAL0_USER="${HAL0_USER}" HAL0_PYTHON="${PY}" \
            HAL0_PREFIX="${HAL0_PREFIX:-}" HAL0_NO_PROBE="${HAL0_NO_PROBE:-}" \
            bash "$0" "$@"
    else
        die "must run as root (sudo bash install.sh)"
    fi
fi

if [[ "${DEV_MODE}" -eq 0 ]] && ! command -v systemctl >/dev/null; then
    die "systemd not found — hal0 v1 requires systemd"
fi
info "system: $(uname -srm)"

if ! command -v "${PY}" >/dev/null; then
    die "python interpreter '${PY}' not found — install with 'apt install python3 python3-venv'"
fi
PY_VER="$(${PY} -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
info "python: ${PY} (${PY_VER})"

if [[ ! "${PY_VER}" =~ ^3\.(11|12|13|14)$ ]]; then
    warn "hal0 is tested on Python 3.11–3.14; ${PY_VER} may not work."
fi

# Soft Docker check — not fatal so the API can come up on hosts that'll
# install Docker later. Slot loads will fail loudly when launched.
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    info "docker: $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo unknown)"
else
    warn "docker is not available — slot launches will fail until it is installed"
fi

step "Filesystem layout"

mkdir -p \
    "${PREFIX}" \
    "${ETC_DIR}/slots" \
    "${VAR_DIR}/models" \
    "${VAR_DIR}/registry" \
    "${VAR_DIR}/slots" \
    "${VAR_DIR}/openwebui" \
    "${VAR_DIR}/cache" \
    "${UNIT_DIR}"
info "directories under ${PREFIX}, ${ETC_DIR}, ${VAR_DIR}"

step "Python environment"

if [[ ! -d "${VENV_DIR}" ]]; then
    "${PY}" -m venv "${VENV_DIR}"
    info "created venv at ${VENV_DIR}"
fi
PIP="${VENV_DIR}/bin/pip"
HAL0_BIN="${VENV_DIR}/bin/hal0"

# Refresh pip + install hal0 in editable mode pointing at this checkout.
${PIP} install --upgrade pip setuptools wheel >/dev/null
${PIP} install -e "${REPO_ROOT}" >/dev/null
info "installed hal0 from ${REPO_ROOT}"

if [[ ! -x "${HAL0_BIN}" ]]; then
    die "hal0 binary not produced at ${HAL0_BIN} — check pip install output"
fi
info "hal0 cli: ${HAL0_BIN}"

step "Configuration"

HAL0_TOML="${ETC_DIR}/hal0.toml"
if [[ ! -f "${HAL0_TOML}" ]]; then
    cat > "${HAL0_TOML}" <<TOML
# hal0 configuration — created by install.sh ($(date -uIseconds))
# Edit with: hal0 config edit
# Validate:  hal0 config validate

[meta]
schema_version = 1

[slots]
port_range_start = 8081
port_range_end = 8099

[dispatcher]
prefetch_timeout_s = 8.0
prefetch_parallel_cap = 4

[telemetry]
enabled = false
TOML
    info "wrote ${HAL0_TOML}"
else
    info "${HAL0_TOML} exists — left alone"
fi

API_ENV="${ETC_DIR}/api.env"
if [[ ! -f "${API_ENV}" ]]; then
    cat > "${API_ENV}" <<EOF
HAL0_PORT=${HAL0_PORT}
HAL0_LOG_LEVEL=info
# Uncomment to pin specific toolbox images:
# HAL0_TOOLBOX_IMAGE_VULKAN=ghcr.io/hal0-dev/hal0-toolbox-vulkan:v1
# HAL0_TOOLBOX_IMAGE_ROCM=ghcr.io/hal0-dev/hal0-toolbox-rocm:v1
EOF
    info "wrote ${API_ENV}"
fi

UPSTREAMS_TOML="${ETC_DIR}/upstreams.toml"
if [[ ! -f "${UPSTREAMS_TOML}" ]]; then
    cat > "${UPSTREAMS_TOML}" <<EOF
# External LLM upstreams — populated via the WebUI Providers tab,
# 'hal0 config edit' here, or directly with the API.
EOF
    info "wrote ${UPSTREAMS_TOML}"
fi

# OpenWebUI prewire env. Rendered via the just-installed venv so the
# defaults live in exactly one place (src/hal0/openwebui/env_writer.py).
# In dev mode we point HAL0_HOME at the prefix so the file lands under
# the dev tree alongside the rest of the config.
HAL0_HOME_FOR_OWUI=""
if [[ "${DEV_MODE}" -eq 1 ]]; then
    HAL0_HOME_FOR_OWUI="${PREFIX}"
fi
if HAL0_HOME="${HAL0_HOME_FOR_OWUI}" "${VENV_DIR}/bin/python" -c \
    'from hal0.openwebui.env_writer import main; main()'; then
    info "wrote ${ETC_DIR}/openwebui.env"
else
    warn "failed to write openwebui.env — OpenWebUI may not start"
fi

step "Systemd units"

API_UNIT="${UNIT_DIR}/hal0-api.service"
cat > "${API_UNIT}" <<EOF
[Unit]
Description=hal0 API daemon
Documentation=https://github.com/hal0-dev/hal0
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${HAL0_USER}
WorkingDirectory=${PREFIX}
EnvironmentFile=${API_ENV}
ExecStart=${HAL0_BIN} serve --host 0.0.0.0 --port \${HAL0_PORT}
Restart=on-failure
RestartSec=3
StandardOutput=journal
StandardError=journal
SyslogIdentifier=hal0-api

[Install]
WantedBy=multi-user.target
EOF
info "wrote ${API_UNIT}"

SLOT_TEMPLATE_SRC="${REPO_ROOT}/packaging/systemd/hal0-slot@.service"
SLOT_TEMPLATE_DST="${UNIT_DIR}/hal0-slot@.service"
if [[ -f "${SLOT_TEMPLATE_SRC}" ]]; then
    cp "${SLOT_TEMPLATE_SRC}" "${SLOT_TEMPLATE_DST}"
    info "wrote ${SLOT_TEMPLATE_DST}"
else
    warn "${SLOT_TEMPLATE_SRC} not found — slot template not installed"
fi

OPENWEBUI_UNIT_SRC="${REPO_ROOT}/packaging/systemd/hal0-openwebui.service"
OPENWEBUI_UNIT_DST="${UNIT_DIR}/hal0-openwebui.service"
if [[ -f "${OPENWEBUI_UNIT_SRC}" ]]; then
    cp "${OPENWEBUI_UNIT_SRC}" "${OPENWEBUI_UNIT_DST}"
    info "wrote ${OPENWEBUI_UNIT_DST}"
else
    warn "${OPENWEBUI_UNIT_SRC} not found — OpenWebUI unit not installed"
fi

if [[ "${DEV_MODE}" -eq 0 ]]; then
    systemctl daemon-reload
    info "systemctl daemon-reload"
fi

# Kick off a background pull of the OpenWebUI image so the unit start
# below isn't blocked by a multi-hundred-MB download on first install.
# The unit also has ExecStartPre=docker pull (idempotent), so a missed
# background pull never breaks correctness — only first-boot latency.
if [[ "${DEV_MODE}" -eq 0 && "${NO_START}" -eq 0 ]] && command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    info "pulling ghcr.io/open-webui/open-webui:main in the background"
    (docker pull ghcr.io/open-webui/open-webui:main >/dev/null 2>&1 || true) &
    disown
fi

step "Hardware probe"

if [[ -z "${HAL0_NO_PROBE:-}" ]]; then
    HAL0_HOME_FOR_PROBE=""
    if [[ "${DEV_MODE}" -eq 1 ]]; then
        HAL0_HOME_FOR_PROBE="${PREFIX}"
    fi
    HAL0_HOME="${HAL0_HOME_FOR_PROBE}" "${VENV_DIR}/bin/python" - <<'PY'
from hal0.hardware.probe import HardwareProbe
p = HardwareProbe()
info = p.probe()
out = p.write(info)
print(f"  wrote {out}")
print(f"  ram_mb={info.ram_mb}  unified={info.unified_memory_mb}  gpus={len(info.gpus)}  npu={info.npu.present}")
PY
else
    warn "skipping probe (HAL0_NO_PROBE=1)"
fi

step "Service start"

if [[ "${DEV_MODE}" -eq 1 || "${NO_START}" -eq 1 ]]; then
    warn "not starting services automatically (dev / --no-start)."
    warn "  start manually: ${HAL0_BIN} serve --host 0.0.0.0 --port ${HAL0_PORT}"
else
    systemctl enable --now hal0-api
    sleep 1
    if systemctl is-active --quiet hal0-api; then
        info "hal0-api is running"
    else
        warn "hal0-api failed to start; check 'journalctl -u hal0-api -n 40'"
    fi

    if [[ -f "${OPENWEBUI_UNIT_DST}" ]]; then
        systemctl enable --now hal0-openwebui
        # OpenWebUI can take a moment to come up while it pulls the
        # image / initialises its sqlite db. Don't fail the installer
        # on a slow first boot; just surface the status.
        sleep 2
        if systemctl is-active --quiet hal0-openwebui; then
            info "hal0-openwebui is running (chat at :3001)"
        else
            warn "hal0-openwebui not yet active; check 'journalctl -u hal0-openwebui -n 40'"
        fi
    fi
fi

HOST="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
[[ -z "${HOST}" ]] && HOST=localhost

printf '\n%shal0 installed.%s\n\n' "${BOLD}${GRN}" "${RST}"
printf '  CLI:        %s%s%s\n' "${BLU}" "${HAL0_BIN}" "${RST}"
printf '  Config:     %s%s%s\n' "${BLU}" "${ETC_DIR}" "${RST}"
printf '  Data:       %s%s%s\n' "${BLU}" "${VAR_DIR}" "${RST}"
if [[ "${DEV_MODE}" -eq 0 && "${NO_START}" -eq 0 ]]; then
    printf '  Dashboard:  %shttp://%s:%s%s\n' "${BLU}" "${HOST}" "${HAL0_PORT}" "${RST}"
    printf '  Chat:       %shttp://%s:3001%s\n' "${BLU}" "${HOST}" "${RST}"
    printf '  Logs:       %sjournalctl -fu hal0-api%s\n' "${DIM}" "${RST}"
fi
printf '\n  Next steps:\n'
printf '    %shal0 status%s          – system + slot summary\n' "${BOLD}" "${RST}"
printf '    %shal0 slot list%s       – list configured slots\n' "${BOLD}" "${RST}"
printf '    %shal0 model list%s      – list known models\n' "${BOLD}" "${RST}"
printf '    %shal0 config show%s     – inspect /etc/hal0/hal0.toml\n' "${BOLD}" "${RST}"
printf '\n'

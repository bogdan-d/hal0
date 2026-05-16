#!/usr/bin/env bash
# hal0 installer — idempotent, non-interactive.
#
# Usage:
#   sudo bash install.sh             # standard install at /opt/hal0
#   bash install.sh --dev            # local-only install under $PWD/.hal0ai
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
# CURRENT_STEP is read by the ERR trap to surface step-specific
# recovery hints. step() updates it; trap below dispatches on it.
CURRENT_STEP=""
step()  { CURRENT_STEP="$*"; printf "\n${BOLD}── %s${RST}\n" "$*"; }
die()   { err "$*"; exit 1; }

# Poll `systemctl is-active` for up to `timeout` seconds. Returns 0 the
# moment the unit reports active, 1 on timeout. Use instead of a flat
# `sleep N; is-active` so slow first boots (OpenWebUI pulling images,
# Caddy provisioning TLS) don't get falsely flagged as failures.
wait_active() {
    local unit="$1" timeout="${2:-15}" deadline=$((SECONDS+timeout))
    while (( SECONDS < deadline )); do
        systemctl is-active --quiet "${unit}" && return 0
        sleep 0.5
    done
    return 1
}

DEV_MODE=0
NO_START=0
AUTH_MODE="off"   # "off" (default) | "basic" (Caddy + Bearer)
for arg in "$@"; do
    case "$arg" in
        --dev) DEV_MODE=1 ;;
        --no-start) NO_START=1 ;;
        --auth=off) AUTH_MODE="off" ;;
        --auth=basic) AUTH_MODE="basic" ;;
        --auth=*)
            warn "unknown --auth value: ${arg} (expected 'off' or 'basic'); using 'off'"
            ;;
        --help|-h)
            cat <<EOF
Usage: install.sh [--dev] [--no-start] [--auth=off|basic]
  --dev          install under \$PWD/.hal0ai/, no systemd setup
  --no-start     set up everything but don't enable/start the API
  --auth=off     no reverse proxy or auth (default; trusted-LAN posture)
  --auth=basic   install Caddy with basic_auth + bearer-token enforcement;
                 the dashboard moves to https://<host>/ on :443
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
    PREFIX="${HAL0_PREFIX:-${PWD}/.hal0ai}"
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

trap 'err "install failed at line ${LINENO} during: ${CURRENT_STEP:-pre-init}"
    case "${CURRENT_STEP}" in
        "Python environment")
            warn "Recovery: scroll up to the pip output for the real error."
            warn "         Retry with HAL0_PYTHON=python3.12 sudo bash install.sh" ;;
        "Service start")
            warn "Recovery: journalctl -u hal0-api -n 60" ;;
        Auth*)
            warn "Recovery: rerun with HAL0_ADMIN_USER=... HAL0_ADMIN_PASSWORD=... set,"
            warn "         or drop --auth=basic to install in the trusted-LAN posture." ;;
        "Hardware probe")
            warn "Recovery: rerun with HAL0_NO_PROBE=1 and file an issue with"
            warn "         /etc/hal0/hardware.json (if present) attached." ;;
    esac
    exit 1' ERR

step "Pre-flight checks"

if [[ "${DEV_MODE}" -eq 0 && "$(id -u)" -ne 0 ]]; then
    if command -v sudo >/dev/null; then
        warn "Re-exec under sudo"
        exec sudo -E HAL0_PORT="${HAL0_PORT}" HAL0_USER="${HAL0_USER}" HAL0_PYTHON="${PY}" \
            HAL0_PREFIX="${HAL0_PREFIX:-}" HAL0_NO_PROBE="${HAL0_NO_PROBE:-}" \
            HAL0_HOSTNAME="${HAL0_HOSTNAME:-}" HAL0_TLS_EMAIL="${HAL0_TLS_EMAIL:-}" \
            HAL0_ADMIN_USER="${HAL0_ADMIN_USER:-}" HAL0_ADMIN_PASSWORD="${HAL0_ADMIN_PASSWORD:-}" \
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

step "Dashboard UI"

UI_DIR="${REPO_DIR}/ui"
UI_DIST="${UI_DIR}/dist"
if [[ -f "${UI_DIST}/index.html" ]]; then
    info "ui/dist already built — left alone"
elif command -v npm >/dev/null 2>&1; then
    info "building ui/dist (npm install + npm run build)"
    (cd "${UI_DIR}" && npm install --no-audit --no-fund --silent && npm run build --silent) \
        || die "ui build failed — check ${UI_DIR}/npm-debug.log"
    info "wrote ${UI_DIST}"
else
    warn "npm not found — dashboard at :${HAL0_PORT}/ will return 404 until you build the UI"
    warn "  install Node 20 LTS, then: cd ${UI_DIR} && npm install && npm run build"
fi

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
# HAL0_TOOLBOX_IMAGE_VULKAN=ghcr.io/hal0ai/hal0-toolbox-vulkan:v1
# HAL0_TOOLBOX_IMAGE_ROCM=ghcr.io/hal0ai/hal0-toolbox-rocm:v1
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

# ── Auth wiring (--auth=basic) ───────────────────────────────────────
# Done BEFORE the openwebui env writer so the OPENWEBUI_AUTH=True +
# trusted-header keys are baked in on the first render rather than
# requiring a second pass.
HAL0_AUTH_ENABLED_FOR_RENDER="0"
if [[ "${AUTH_MODE}" == "basic" ]]; then
    if [[ "${DEV_MODE}" -eq 1 ]]; then
        warn "--auth=basic with --dev is unsupported (no system Caddy install); skipping auth setup"
        AUTH_MODE="off"
    else
        step "Auth (Caddy basic_auth + Bearer)"

        # Caddy install — Debian/Ubuntu via apt, Arch/CachyOS via pacman.
        # Anything else falls through with a manual-install hint.
        if ! command -v caddy >/dev/null; then
            if command -v apt-get >/dev/null; then
                info "installing caddy via apt"
                apt-get update -qq
                # The official caddy package on Debian needs a third-party
                # repo; for a polished installer we pin to the cloudsmith
                # mirror in a v0.3 follow-up. For the POC, surface the
                # missing-binary path so an operator can apt install caddy
                # by hand and re-run.
                APT_ERR="$(mktemp)"
                if ! apt-get install -y caddy 2>"${APT_ERR}"; then
                    warn "apt failed to install caddy:"
                    sed 's/^/    /' "${APT_ERR}" >&2
                    warn "Install per https://caddyserver.com/docs/install#debian-ubuntu-raspbian and re-run."
                fi
                rm -f "${APT_ERR}"
            elif command -v pacman >/dev/null; then
                info "installing caddy via pacman"
                pacman -S --noconfirm caddy
            else
                warn "no recognised package manager for caddy; install it from https://caddyserver.com/docs/install and re-run"
            fi
        fi
        if ! command -v caddy >/dev/null; then
            die "caddy binary not on PATH after install attempt — see warnings above"
        fi
        info "caddy: $(caddy version 2>/dev/null | head -n1 || echo unknown)"

        # Admin credentials — env-driven for non-interactive installs,
        # interactive prompts otherwise. Both paths feed into Caddy's
        # `caddy hash-password` for the bcrypt hash baked into the
        # Caddyfile.
        if [[ -z "${HAL0_ADMIN_USER:-}" ]]; then
            if [[ -t 0 ]]; then
                read -r -p "Admin username [admin]: " HAL0_ADMIN_USER
                HAL0_ADMIN_USER="${HAL0_ADMIN_USER:-admin}"
            else
                HAL0_ADMIN_USER="admin"
            fi
        fi
        if [[ -z "${HAL0_ADMIN_PASSWORD:-}" ]]; then
            if [[ -t 0 ]]; then
                # Read silently; -s isn't POSIX so we fall back if missing.
                printf "Admin password (will not echo): "
                read -r -s HAL0_ADMIN_PASSWORD
                printf "\n"
                if [[ -z "${HAL0_ADMIN_PASSWORD}" ]]; then
                    die "admin password must not be empty"
                fi
            else
                die "non-interactive --auth=basic requires HAL0_ADMIN_USER + HAL0_ADMIN_PASSWORD env vars"
            fi
        fi

        HAL0_HOSTNAME="${HAL0_HOSTNAME:-hal0.local}"
        HAL0_TLS_EMAIL="${HAL0_TLS_EMAIL:-admin@${HAL0_HOSTNAME}}"

        # bcrypt hash via caddy's own helper. `--plaintext` reads from
        # the flag rather than stdin so the password never lands on the
        # process's argv (the flag itself becomes part of `ps` output —
        # acceptable on a single-user install host but documented).
        HAL0_ADMIN_PASSWORD_HASH="$(caddy hash-password --plaintext "${HAL0_ADMIN_PASSWORD}")"
        if [[ -z "${HAL0_ADMIN_PASSWORD_HASH}" ]]; then
            die "caddy hash-password returned empty hash"
        fi
        info "hashed admin password for ${HAL0_ADMIN_USER}"

        # Render the Caddyfile from the template. envsubst would be
        # cleaner; use a portable sed pipeline so we don't need to add
        # a coreutils dep on minimal hosts.
        CADDY_TEMPLATE="${REPO_ROOT}/packaging/caddy/Caddyfile.template"
        CADDY_TARGET="${ETC_DIR}/Caddyfile"
        if [[ ! -f "${CADDY_TEMPLATE}" ]]; then
            die "Caddyfile template missing at ${CADDY_TEMPLATE}"
        fi
        # Use python for the substitution so password hashes containing
        # '/', '$', '&' don't trip up sed escape rules.
        HAL0_HOSTNAME="${HAL0_HOSTNAME}" \
        HAL0_TLS_EMAIL="${HAL0_TLS_EMAIL}" \
        HAL0_ADMIN_USER="${HAL0_ADMIN_USER}" \
        HAL0_ADMIN_PASSWORD_HASH="${HAL0_ADMIN_PASSWORD_HASH}" \
        "${PY}" - "${CADDY_TEMPLATE}" "${CADDY_TARGET}" <<'PY'
import os, sys, string
src, dst = sys.argv[1], sys.argv[2]
text = open(src).read()
# Caddy's own ${VAR:default} placeholder syntax is what the template
# uses inside its config — preserve those by only substituting the
# specific keys we know about. Anything else is passed through verbatim
# so Caddy's runtime substitution still works.
keys = ("HAL0_HOSTNAME", "HAL0_TLS_EMAIL", "HAL0_ADMIN_USER", "HAL0_ADMIN_PASSWORD_HASH")
for k in keys:
    val = os.environ.get(k, "")
    # Replace `{$KEY:default}` and `{$KEY}` forms with the resolved
    # value at install time so the running Caddy config doesn't depend
    # on systemd-passing the env var.
    text = text.replace("{$" + k + "}", val)
    # Match {$KEY:default} regardless of default value.
    while True:
        marker = "{$" + k + ":"
        i = text.find(marker)
        if i < 0:
            break
        j = text.find("}", i)
        if j < 0:
            break
        text = text[:i] + val + text[j+1:]
open(dst, "w").write(text)
# 0644 so the unprivileged 'caddy' user can read the rendered file.
# The bcrypt hash inside is a hash, not a recoverable secret, and the
# hostname / TLS email are public; nothing here justifies 0640 + chown.
os.chmod(dst, 0o644)
print(f"  rendered {dst}")
PY
        info "wrote ${CADDY_TARGET}"

        # systemd unit drop-in.
        CADDY_UNIT_SRC="${REPO_ROOT}/packaging/systemd/hal0-caddy.service"
        CADDY_UNIT_DST="${UNIT_DIR}/hal0-caddy.service"
        if [[ -f "${CADDY_UNIT_SRC}" ]]; then
            cp "${CADDY_UNIT_SRC}" "${CADDY_UNIT_DST}"
            info "wrote ${CADDY_UNIT_DST}"
        else
            warn "${CADDY_UNIT_SRC} not found — Caddy unit not installed"
        fi

        # Avahi (best-effort).
        if command -v avahi-daemon >/dev/null && [[ -d /etc/avahi/services ]]; then
            cp "${REPO_ROOT}/packaging/avahi/hal0.service" /etc/avahi/services/hal0.service
            info "wrote /etc/avahi/services/hal0.service (mDNS announcing ${HAL0_HOSTNAME})"
        else
            warn "avahi-daemon not present; add an /etc/hosts entry on clients: '<this-host-ip> ${HAL0_HOSTNAME}'"
        fi

        # Flip the runtime auth flag for hal0-api.
        if [[ -f "${API_ENV}" ]]; then
            # Replace any existing line, else append.
            if grep -q '^HAL0_AUTH_ENABLED=' "${API_ENV}"; then
                sed -i 's|^HAL0_AUTH_ENABLED=.*|HAL0_AUTH_ENABLED=1|' "${API_ENV}"
            else
                echo "HAL0_AUTH_ENABLED=1" >> "${API_ENV}"
            fi
            info "set HAL0_AUTH_ENABLED=1 in ${API_ENV}"
        fi
        HAL0_AUTH_ENABLED_FOR_RENDER="1"
    fi
fi

# OpenWebUI prewire env. Rendered via the just-installed venv so the
# defaults live in exactly one place (src/hal0/openwebui/env_writer.py).
# In dev mode we point HAL0_HOME at the prefix so the file lands under
# the dev tree alongside the rest of the config.
HAL0_HOME_FOR_OWUI=""
if [[ "${DEV_MODE}" -eq 1 ]]; then
    HAL0_HOME_FOR_OWUI="${PREFIX}"
fi
# HAL0_AUTH_ENABLED in the calling env flips OpenWebUI prewire defaults
# to single-sign-on (WEBUI_AUTH=True + WEBUI_AUTH_TRUSTED_EMAIL_HEADER).
if HAL0_HOME="${HAL0_HOME_FOR_OWUI}" HAL0_AUTH_ENABLED="${HAL0_AUTH_ENABLED_FOR_RENDER}" \
    "${VENV_DIR}/bin/python" -c \
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
Documentation=https://github.com/hal0ai/hal0
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
    if wait_active hal0-api 15; then
        info "hal0-api is running"
    else
        warn "hal0-api failed to start; check 'journalctl -u hal0-api -n 40'"
    fi

    if [[ -f "${OPENWEBUI_UNIT_DST}" ]]; then
        systemctl enable --now hal0-openwebui
        # OpenWebUI can take a moment to come up while it pulls the
        # image / initialises its sqlite db. Don't fail the installer
        # on a slow first boot; just surface the status.
        if wait_active hal0-openwebui 30; then
            info "hal0-openwebui is running (chat at :3001)"
        else
            warn "hal0-openwebui not yet active; check 'journalctl -u hal0-openwebui -n 40'"
        fi
    fi

    # If --auth=basic was selected, start Caddy too. Restart hal0-api so
    # the new HAL0_AUTH_ENABLED=1 takes effect and the ports flip from
    # the open posture to "Caddy fronts everything".
    if [[ "${AUTH_MODE}" == "basic" && -f "${UNIT_DIR}/hal0-caddy.service" ]]; then
        systemctl restart hal0-api
        systemctl restart hal0-openwebui || true
        systemctl enable --now hal0-caddy
        sleep 1
        if systemctl is-active --quiet hal0-caddy; then
            info "hal0-caddy is running (https://${HAL0_HOSTNAME:-hal0.local}/)"
        else
            warn "hal0-caddy not yet active; check 'journalctl -u hal0-caddy -n 60'"
        fi
        # Reload avahi so the freshly-dropped service file is announced
        # (best-effort — failing reload doesn't break anything).
        if command -v systemctl >/dev/null && systemctl is-active --quiet avahi-daemon; then
            systemctl reload avahi-daemon || true
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
    if [[ "${AUTH_MODE}" == "basic" ]]; then
        HOSTNAME_FOR_DISPLAY="${HAL0_HOSTNAME:-hal0.local}"
        printf '  Dashboard:  %shttps://%s/%s\n' "${BLU}" "${HOSTNAME_FOR_DISPLAY}" "${RST}"
        printf '  Chat:       %shttps://%s/chat/%s\n' "${BLU}" "${HOSTNAME_FOR_DISPLAY}" "${RST}"
        printf '  Auth:       %sbasic_auth (admin: %s) + Bearer tokens at /api/auth/tokens%s\n' "${DIM}" "${HAL0_ADMIN_USER:-admin}" "${RST}"
        printf '  Logs:       %sjournalctl -fu hal0-caddy hal0-api hal0-openwebui%s\n' "${DIM}" "${RST}"
    else
        printf '  Dashboard:  %shttp://%s:%s%s\n' "${BLU}" "${HOST}" "${HAL0_PORT}" "${RST}"
        printf '  Chat:       %shttp://%s:3001%s\n' "${BLU}" "${HOST}" "${RST}"
        printf '  Logs:       %sjournalctl -fu hal0-api%s\n' "${DIM}" "${RST}"
    fi
fi
printf '\n  Next steps:\n'
printf '    %shal0 status%s          – system + slot summary\n' "${BOLD}" "${RST}"
printf '    %shal0 slot list%s       – list configured slots\n' "${BOLD}" "${RST}"
printf '    %shal0 model list%s      – list known models\n' "${BOLD}" "${RST}"
printf '    %shal0 config show%s     – inspect /etc/hal0/hal0.toml\n' "${BOLD}" "${RST}"
printf '\n'

#!/usr/bin/env bash
# hal0 uninstaller
#
# Usage:
#   sudo bash uninstall.sh             # stops services, prompts before deleting data
#   sudo bash uninstall.sh --keep-data # leaves /etc/hal0 and /var/lib/hal0 intact
#   HAL0_FORCE=1 sudo bash uninstall.sh # no confirmation prompt

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
KEEP_DATA=0
HAL0_FORCE="${HAL0_FORCE:-0}"

for arg in "$@"; do
    case "$arg" in
        --keep-data) KEEP_DATA=1 ;;
        --force)     HAL0_FORCE=1 ;;
        --help|-h)
            printf 'Usage: uninstall.sh [--keep-data] [--force]\n'
            printf '  --keep-data  preserve /etc/hal0 and /var/lib/hal0\n'
            printf '  --force      skip data-deletion confirmation prompt\n'
            printf '  HAL0_FORCE=1 env var is equivalent to --force\n'
            exit 0
            ;;
        *) warn "Unknown flag: $arg (ignored)" ;;
    esac
done

# ── Root check ────────────────────────────────────────────────────────────────
if [[ "$(id -u)" -ne 0 ]]; then
    if command -v sudo &>/dev/null; then
        exec sudo bash "$0" "$@"
    else
        die "Must run as root or have sudo available."
    fi
fi

trap 'error "Uninstall failed at line ${LINENO}."; exit 1' ERR

# ── Stop + disable units ──────────────────────────────────────────────────────
step "Stopping services"

UNITS=(hal0-api hal0-openwebui)

# Discover any running slot instances
while IFS= read -r UNIT; do
    UNITS+=("${UNIT%.service}")
done < <(systemctl list-units --type=service --all --no-legend 2>/dev/null \
    | awk '{print $1}' | grep '^hal0-slot@' || true)

for UNIT in "${UNITS[@]}"; do
    if systemctl is-active "${UNIT}" &>/dev/null 2>&1; then
        if systemctl stop "${UNIT}"; then
            info "Stopped ${UNIT}"
        else
            warn "Could not stop ${UNIT} (may already be stopped)"
        fi
    else
        info "${UNIT} not running"
    fi
    if systemctl is-enabled "${UNIT}" &>/dev/null 2>&1; then
        if systemctl disable "${UNIT}"; then
            info "Disabled ${UNIT}"
        else
            warn "Could not disable ${UNIT}"
        fi
    fi
done

# Stop OpenWebUI container explicitly in case docker didn't get the memo
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^hal0-openwebui$'; then
    docker stop hal0-openwebui &>/dev/null || true
    info "Stopped Docker container hal0-openwebui"
fi

# ── Remove unit files ─────────────────────────────────────────────────────────
step "Removing systemd units"

UNIT_DIR="/etc/systemd/system"
for UNIT_FILE in \
    "${UNIT_DIR}/hal0-api.service" \
    "${UNIT_DIR}/hal0-openwebui.service" \
    "${UNIT_DIR}/hal0-slot@.service"
do
    if [[ -f "${UNIT_FILE}" ]]; then
        rm -f "${UNIT_FILE}"
        info "Removed ${UNIT_FILE}"
    else
        info "${UNIT_FILE} not present"
    fi
done

systemctl daemon-reload
info "systemctl daemon-reload done"

# ── Remove code ───────────────────────────────────────────────────────────────
step "Removing /usr/lib/hal0"

if [[ -d /usr/lib/hal0 ]] || [[ -L /usr/lib/hal0/current ]]; then
    rm -rf /usr/lib/hal0
    info "Removed /usr/lib/hal0"
else
    info "/usr/lib/hal0 not present"
fi

# ── PATH symlink ──────────────────────────────────────────────────────────────
HAL0_PATH_LINK="${HAL0_PATH_LINK:-/usr/local/bin/hal0}"
if [[ -L "${HAL0_PATH_LINK}" ]] || [[ -f "${HAL0_PATH_LINK}" ]]; then
    rm -f "${HAL0_PATH_LINK}"
    info "Removed ${HAL0_PATH_LINK}"
else
    info "${HAL0_PATH_LINK} not present"
fi

# ── Data dirs ─────────────────────────────────────────────────────────────────
step "Data directories"

if [[ "${KEEP_DATA}" -eq 1 ]]; then
    warn "Keeping data dirs (--keep-data):"
    warn "  /etc/hal0      — config"
    warn "  /var/lib/hal0  — models, registry, openwebui state"
    warn "Re-run install.sh to restore services using this data."
else
    # Confirmation unless forced
    if [[ "${HAL0_FORCE}" -ne 1 ]]; then
        printf '\n%s%sWARNING:%s This will delete:\n' "${RED}" "${BOLD}" "${RESET}"
        printf '  /etc/hal0      (config + slot definitions)\n'
        printf '  /var/lib/hal0  (models, registry, openwebui state)\n\n'
        printf 'Type %sDELETE%s to confirm, or Ctrl-C to cancel: ' "${BOLD}" "${RESET}"
        read -r CONFIRM
        if [[ "${CONFIRM}" != "DELETE" ]]; then
            warn "Aborted — data preserved."
            exit 0
        fi
    fi

    for DATA_DIR in /etc/hal0 /var/lib/hal0; do
        if [[ -d "${DATA_DIR}" ]]; then
            rm -rf "${DATA_DIR}"
            info "Removed ${DATA_DIR}"
        else
            info "${DATA_DIR} not present"
        fi
    done
fi

# ── System user ───────────────────────────────────────────────────────────────
step "System user"

if id hal0 &>/dev/null 2>&1; then
    if userdel hal0; then
        info "Removed system user hal0"
    else
        warn "Could not remove hal0 user"
    fi
else
    info "System user hal0 not present"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
printf '\n%s%shal0 uninstalled.%s\n' "${GREEN}" "${BOLD}" "${RESET}"
if [[ "${KEEP_DATA}" -eq 1 ]]; then
    printf '  Config + data preserved in /etc/hal0 and /var/lib/hal0.\n\n'
fi

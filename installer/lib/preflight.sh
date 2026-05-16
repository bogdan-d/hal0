#!/usr/bin/env bash
# installer/lib/preflight.sh — re-runnable pre-flight checks.
#
# Sourceable: install.sh dot-sources this to do its inline preflight.
# Executable: `bash installer/lib/preflight.sh` runs preflight_all and
#             exits with the aggregate status. `hal0 doctor` shells
#             this in executable mode.
#
# Public API (all functions return 0 on success, non-zero on failure;
# none of them exit the calling shell):
#   preflight_systemd          — systemctl on PATH
#   preflight_python           — `${PY:-python3}` resolvable + version 3.11–3.14
#   preflight_docker           — `docker info` reachable (soft; returns 0 with
#                                a warning, since the API can run without
#                                Docker until a slot is launched)
#   preflight_disk MIN_GB DIR  — at least MIN_GB free in DIR (default 20 / /var/lib)
#   preflight_ports P1 [P2…]   — none of the named TCP ports are LISTENing
#   preflight_all              — run all of the above; aggregate non-zero
#
# Globals honoured
#   HAL0_PY            — python interpreter (default python3)
#   HAL0_DISK_MIN_GB   — preflight_disk threshold (default 20)
#   HAL0_DISK_TARGET   — preflight_disk target directory (default /var/lib;
#                        falls back to /tmp if /var/lib is absent — useful
#                        when running `hal0 doctor` on a fresh container)
#   HAL0_DOCTOR_PORTS  — space-separated port list for preflight_ports
#                        (default "8080 3001")

# shellcheck shell=bash

set -o pipefail

# Source ui.sh for `info`/`warn`/`err`/`die` if they aren't already
# defined.  When install.sh sources us, it has already sourced ui.sh and
# `info` is in scope; the guard prevents a second source call.
if ! declare -F info >/dev/null 2>&1; then
    # shellcheck source=ui.sh
    source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ui.sh"
fi

# ── individual checks ───────────────────────────────────────────────────────

preflight_systemd() {
    if command -v systemctl >/dev/null 2>&1; then
        info "systemd: $(systemctl --version 2>/dev/null | head -n1 || echo present)"
        return 0
    fi
    err "systemd not found — hal0 v1 requires systemctl on PATH"
    return 1
}

preflight_python() {
    local py="${HAL0_PY:-${HAL0_PYTHON:-python3}}"
    if ! command -v "${py}" >/dev/null 2>&1; then
        err "python interpreter '${py}' not found"
        warn "  install with 'apt install python3 python3-venv' or set HAL0_PYTHON=..."
        return 1
    fi
    local ver
    if ! ver="$("${py}" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2>/dev/null)"; then
        err "could not read Python version from ${py}"
        return 1
    fi
    if [[ "${ver}" =~ ^3\.(11|12|13|14)$ ]]; then
        info "python: ${py} (${ver})"
        return 0
    fi
    warn "python: ${py} (${ver}) — hal0 is tested on 3.11–3.14"
    return 1
}

preflight_docker() {
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        info "docker: $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo unknown)"
        return 0
    fi
    warn "docker is not available — slot launches will fail until it is installed"
    # Soft check — return 0 so preflight_all stays green when the API
    # can still come up without Docker.  Operators who need Docker
    # right now will see the warning.
    return 0
}

preflight_disk() {
    local min_gb="${1:-${HAL0_DISK_MIN_GB:-20}}"
    local target="${2:-${HAL0_DISK_TARGET:-/var/lib}}"
    # Fall back to /tmp when /var/lib is absent (containerised doctor runs).
    if [[ ! -d "${target}" ]]; then
        target="/tmp"
    fi
    local avail_kb
    avail_kb="$(df -Pk "${target}" 2>/dev/null | awk 'NR==2 {print $4}')"
    if [[ -z "${avail_kb}" ]]; then
        warn "disk: could not read free space on ${target} (df failed)"
        return 1
    fi
    local avail_gb=$(( avail_kb / 1024 / 1024 ))
    if (( avail_gb >= min_gb )); then
        info "disk: ${avail_gb} GB free on ${target} (need ${min_gb})"
        return 0
    fi
    err "disk: only ${avail_gb} GB free on ${target}; need at least ${min_gb} GB"
    return 1
}

# Detect a TCP listener on a port without requiring lsof / netstat:
# prefer `ss`, fall back to /proc/net/tcp{,6} for the static-binary case.
_preflight_port_in_use() {
    local port="$1" hex
    if command -v ss >/dev/null 2>&1; then
        ss -ltn "sport = :${port}" 2>/dev/null | awk 'NR>1 {found=1} END {exit !found}'
        return $?
    fi
    if [[ -r /proc/net/tcp ]]; then
        printf -v hex '%04X' "${port}"
        # State 0A == LISTEN
        awk -v hex=":${hex}" '$2 ~ hex"$" && $4 == "0A" {found=1} END {exit !found}' \
            /proc/net/tcp /proc/net/tcp6 2>/dev/null
        return $?
    fi
    # No tool to check — assume not in use; surface a warning so the
    # operator knows the check was skipped.
    warn "port ${port}: cannot probe (no ss, no /proc/net/tcp); skipping"
    return 1
}

preflight_ports() {
    local ports=("$@")
    if (( ${#ports[@]} == 0 )); then
        # Default to the API + OpenWebUI ports the installer binds to.
        # Caller can pass an explicit list to widen this.
        local default_ports="${HAL0_DOCTOR_PORTS:-8080 3001}"
        # shellcheck disable=SC2206  # intentional word-split on the env var
        ports=( ${default_ports} )
    fi
    local rc=0 port
    for port in "${ports[@]}"; do
        if _preflight_port_in_use "${port}"; then
            err "port ${port}: already in use (find with 'ss -ltnp \"sport = :${port}\"')"
            rc=1
        else
            info "port ${port}: free"
        fi
    done
    return "${rc}"
}

# ── aggregate runner ────────────────────────────────────────────────────────

# Run every check; return non-zero if any failed. We deliberately don't
# short-circuit — operators expect `hal0 doctor` to surface the full
# picture, not the first failure.
preflight_all() {
    local rc=0
    preflight_systemd || rc=$?
    preflight_python  || rc=$?
    preflight_docker  || rc=$?
    preflight_disk    || rc=$?
    preflight_ports   || rc=$?
    if (( rc == 0 )); then
        info "all pre-flight checks passed"
    else
        err "one or more pre-flight checks failed (see above)"
    fi
    return "${rc}"
}

# ── executable entry point ──────────────────────────────────────────────────
# Only fires when this file is invoked directly (e.g.
# `bash installer/lib/preflight.sh` or via `hal0 doctor`). When sourced
# from install.sh, BASH_SOURCE[0] != $0 and we no-op so the caller can
# pick which checks to run.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    preflight_all
    exit $?
fi

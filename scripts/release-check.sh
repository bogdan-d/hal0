#!/usr/bin/env bash
# hal0 release-check — pre-release gate ritual
#
# Phase 6 target: full matrix across Vulkan / ROCm / NPU on hal0-test LXC.
# Phase 0: stub — validates what exists and notes what's missing.
#
# Usage:
#   bash scripts/release-check.sh [--channel stable|nightly]

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
warn()  { printf "${YELLOW}!${RESET}  %s\n" "$*"; }
fail()  { printf "${RED}✗${RESET}  %s\n" "$*" >&2; FAILURES=$(( FAILURES + 1 )); }
step()  { printf "\n${BOLD}── %s${RESET}\n" "$*"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHANNEL="${HAL0_CHANNEL:-stable}"
FAILURES=0

for arg in "$@"; do
    case "$arg" in
        --channel=*) CHANNEL="${arg#--channel=}" ;;
        --channel)   shift; CHANNEL="$1" ;;
    esac
done

# ── Toolbox image version checks ──────────────────────────────────────────────
step "Toolbox image versions"

MANIFEST="${REPO_ROOT}/src/hal0/manifest.json"
if [[ -f "${MANIFEST}" ]]; then
    info "manifest.json found"
    # Verify each toolbox image tag is a pinned digest or semver (not 'latest')
    while IFS= read -r IMAGE; do
        if [[ "${IMAGE}" == *":latest" ]]; then
            fail "Unpinned image tag 'latest': ${IMAGE}. Pin to a semver or digest."
        elif [[ "${IMAGE}" =~ ^ghcr\.io/hal0-dev/ ]]; then
            info "Image OK: ${IMAGE}"
        fi
    done < <(grep -o '"ghcr\.io/hal0-dev/[^"]*"' "${MANIFEST}" | tr -d '"' || true)
else
    warn "manifest.json not found at ${MANIFEST} (Phase 0 — no toolbox images yet)"
    warn "TODO Phase 2: create manifest.json with pinned toolbox image digests"
fi

# ── Lint ──────────────────────────────────────────────────────────────────────
step "Lint"

if command -v ruff &>/dev/null; then
    if ruff check "${REPO_ROOT}/src/" 2>&1; then
        info "ruff: clean"
    else
        fail "ruff found lint errors — fix before release"
    fi
else
    warn "ruff not installed — skipping Python lint (pip install ruff)"
fi

if command -v shellcheck &>/dev/null; then
    SC_ERRORS=0
    for SCRIPT in \
        "${REPO_ROOT}/installer/install.sh" \
        "${REPO_ROOT}/installer/uninstall.sh" \
        "${REPO_ROOT}/installer/bin/hal0-slot-launch" \
        "${REPO_ROOT}/scripts/dev-bootstrap.sh" \
        "${REPO_ROOT}/scripts/release-check.sh"
    do
        if [[ -f "${SCRIPT}" ]]; then
            if shellcheck "${SCRIPT}" 2>&1; then
                info "shellcheck OK: $(basename "${SCRIPT}")"
            else
                fail "shellcheck: errors in $(basename "${SCRIPT}")"
                SC_ERRORS=$(( SC_ERRORS + 1 ))
            fi
        fi
    done
    [[ "${SC_ERRORS}" -eq 0 ]] && info "All shell scripts clean"
else
    warn "shellcheck not installed — skipping shell lint (pacman -S shellcheck)"
fi

# ── Tests ─────────────────────────────────────────────────────────────────────
step "Tests"

if command -v pytest &>/dev/null; then
    if pytest "${REPO_ROOT}/tests/" -q 2>&1; then
        info "pytest: all tests passed"
    else
        fail "pytest: test failures — fix before release"
    fi
else
    warn "pytest not installed — skipping (pip install pytest)"
fi

# ── Installer syntax check ────────────────────────────────────────────────────
step "Installer syntax"

for SCRIPT in \
    "${REPO_ROOT}/installer/install.sh" \
    "${REPO_ROOT}/installer/uninstall.sh" \
    "${REPO_ROOT}/installer/bin/hal0-slot-launch" \
    "${REPO_ROOT}/scripts/dev-bootstrap.sh" \
    "${REPO_ROOT}/scripts/release-check.sh"
do
    if [[ -f "${SCRIPT}" ]]; then
        if bash -n "${SCRIPT}" 2>&1; then
            info "Syntax OK: $(basename "${SCRIPT}")"
        else
            fail "Syntax error: $(basename "${SCRIPT}")"
        fi
    fi
done

# ── Deferred release-gate checks ─────────────────────────────────────────────
step "Deferred gates (Phase 6)"

warn "TODO: full release-gate matrix (Phase 6):"
warn "  - Vulkan-CPU slot integration test (Qwen3 0.5B)"
warn "  - ROCm slot integration test on hal0-test LXC"
warn "  - NPU (FLM) slot integration test on hal0-test LXC"
warn "  - Playwright γ tests (7 critical paths)"
warn "  - cosign signature verification of release tarball"
warn "  - hal0 update --rollback round-trip"
warn "  - OpenWebUI prewire smoke test (chat request end-to-end)"

# ── Summary ───────────────────────────────────────────────────────────────────
printf "\n"
if [[ "${FAILURES}" -eq 0 ]]; then
    printf "${GREEN}${BOLD}Release check passed${RESET} (channel: %s)\n\n" "${CHANNEL}"
    exit 0
else
    printf "${RED}${BOLD}Release check FAILED${RESET} — %d check(s) failed.\n\n" "${FAILURES}"
    exit 1
fi

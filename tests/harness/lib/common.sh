#!/usr/bin/env bash
# tests/harness/lib/common.sh
#
# Shared helpers for the hal0 test harness. Sourced by every tier
# (installer-test.sh, cli-test.sh, runtime-test.sh) so every row in
# every report uses the same JSON shape that scripts/release-test.sh
# already emits — i.e. tests/release-gate-report.json schema.
#
# Public API (after sourcing):
#   harness_init <tier_name> <report_path>
#       Resets ROWS_JSON, captures meta. Tier name is "installer", "cli",
#       or "runtime"; report_path is where harness_write_report dumps the
#       final JSON file. Call once at the top of a tier script.
#
#   add_row <name> <status:pass|fail|skip|deferred> <duration_ms> <detail>
#       Appends a structured row to the in-memory accumulator and prints
#       a colourised one-liner. Mirrors release-test.sh:117–132.
#
#   start_ms / since_ms <start>
#       Wall-clock helpers. start_ms returns ns; since_ms returns int ms.
#
#   log_step / log_info / log_warn / log_err
#       Tee-friendly status prints.
#
#   harness_write_report
#       Serialises {schema, generated, tier, host, summary, rows} to the
#       path passed to harness_init. Returns 1 if any row is "fail".
#
# Design notes:
#   - Bash 5+ associative-array safe; tested under set -euo pipefail.
#   - JSON assembly delegated to python3 to keep quoting safe.
#   - Each tier writes its own report file; scripts/harness.sh merges.

set -euo pipefail
IFS=$'\n\t'

# ── colours ──────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    H_RED=$'\033[0;31m'; H_YEL=$'\033[1;33m'; H_GRN=$'\033[0;32m'
    H_BLU=$'\033[0;36m'; H_BOLD=$'\033[1m';   H_DIM=$'\033[2m'; H_RST=$'\033[0m'
else
    H_RED=; H_YEL=; H_GRN=; H_BLU=; H_BOLD=; H_DIM=; H_RST=
fi
log_info() { printf "${H_GRN}✔${H_RST}  %s\n" "$*"; }
log_warn() { printf "${H_YEL}!${H_RST}  %s\n" "$*" >&2; }
log_err()  { printf "${H_RED}✗${H_RST}  %s\n" "$*" >&2; }
log_step() { printf "\n${H_BOLD}── %s${H_RST}\n" "$*"; }

# ── timing ───────────────────────────────────────────────────────────────────
start_ms() { date +%s%N; }
since_ms() {
    local start="$1" end
    end=$(date +%s%N)
    echo $(( (end - start) / 1000000 ))
}

# ── row accumulator ──────────────────────────────────────────────────────────
ROWS_JSON=()
HARNESS_TIER=""
HARNESS_REPORT_PATH=""
HARNESS_HOST="$(hostname -f 2>/dev/null || hostname)"

harness_init() {
    HARNESS_TIER="${1:?tier name required}"
    HARNESS_REPORT_PATH="${2:?report path required}"
    ROWS_JSON=()
    mkdir -p "$(dirname "${HARNESS_REPORT_PATH}")"
}

add_row() {
    local name="$1" status="$2" dur="$3" detail="$4"
    ROWS_JSON+=("$(python3 - "$name" "$status" "$dur" "$detail" <<'PY'
import json, sys
print(json.dumps({
    "name": sys.argv[1],
    "status": sys.argv[2],
    "duration_ms": int(sys.argv[3]),
    "detail": sys.argv[4],
}))
PY
    )")
    case "${status}" in
        pass)     log_info "[${name}] pass (${dur}ms) — ${detail}" ;;
        fail)     log_err  "[${name}] FAIL (${dur}ms) — ${detail}" ;;
        skip)     log_warn "[${name}] skip — ${detail}" ;;
        deferred) log_warn "[${name}] deferred — ${detail}" ;;
        *)        log_err  "[${name}] BAD STATUS '${status}'" ;;
    esac
}

harness_write_report() {
    if [[ -z "${HARNESS_REPORT_PATH}" ]]; then
        log_err "harness_init never called"
        return 2
    fi

    python3 - "${HARNESS_REPORT_PATH}" "${HARNESS_TIER}" "${HARNESS_HOST}" "${ROWS_JSON[@]}" <<'PY'
import json, sys, time
from pathlib import Path

out_path = Path(sys.argv[1])
tier     = sys.argv[2]
host     = sys.argv[3]
rows     = [json.loads(r) for r in sys.argv[4:]]

report = {
    "_schema":   "hal0.harness-report.v1",
    "generated": int(time.time()),
    "tier":      tier,
    "host":      host,
    "summary": {
        "total":    len(rows),
        "pass":     sum(1 for r in rows if r["status"] == "pass"),
        "fail":     sum(1 for r in rows if r["status"] == "fail"),
        "skip":     sum(1 for r in rows if r["status"] == "skip"),
        "deferred": sum(1 for r in rows if r["status"] == "deferred"),
    },
    "rows": rows,
}
out_path.write_text(json.dumps(report, indent=2) + "\n")
print(f"wrote {out_path}")
PY

    local fails=0
    for row in "${ROWS_JSON[@]}"; do
        if grep -q '"status": "fail"' <<<"${row}"; then
            fails=$(( fails + 1 ))
        fi
    done
    return "${fails}"
}

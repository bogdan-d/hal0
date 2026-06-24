#!/usr/bin/env python3
"""Aggregate per-run llama-bench JSON into a single Hal0-ready index.json and a
human SUMMARY.md (ROCm vs Vulkan comparison).

Each file in <results>/runs/<name>.json is the raw JSON array emitted by
`llama-bench -o json` (one row per pp/tg test). The sibling <name>.meta.json
(written by run_benchmarks.sh) carries our labels: backend, image, context,
tag, host, gpu, timestamp. We flatten every row into a normalized record, write
<results>/index.json, and render <results>/SUMMARY.md.

Schema kept compatible with the llama-bench fields already used in the platform's
benchmark history so the datasets can later merge.

Results dir resolution: argv[1] > $HAL0_BENCH_RESULTS > /var/lib/hal0/benchmarks
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

if len(sys.argv) > 1:
    RESULT_DIR = sys.argv[1]
else:
    RESULT_DIR = os.environ.get("HAL0_BENCH_RESULTS", "/var/lib/hal0/benchmarks")
RUNS_DIR = os.path.join(RESULT_DIR, "runs")


def test_kind(row):
    """pp (prompt processing) vs tg (token generation) for a llama-bench row."""
    if int(row.get("n_gen", 0) or 0) > 0 and int(row.get("n_prompt", 0) or 0) == 0:
        return "tg"
    if int(row.get("n_prompt", 0) or 0) > 0 and int(row.get("n_gen", 0) or 0) == 0:
        return "pp"
    return "mixed"


def load_meta(json_path):
    meta_path = json_path[: -len(".json")] + ".meta.json"
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    return {}


def normalize(row, meta, mtime_iso):
    return {
        "timestamp": meta.get("timestamp") or mtime_iso,
        "host": meta.get("host"),
        "gpu": meta.get("gpu") or row.get("gpu_info"),
        "gpu_info": row.get("gpu_info"),
        "cpu_info": row.get("cpu_info"),
        "backend": meta.get("backend"),
        "backends_reported": row.get("backends"),
        "runtime_image": meta.get("image"),
        "context": meta.get("context", "default"),
        "tag": meta.get("tag", ""),
        "llamacpp_build": {
            "commit": row.get("build_commit"),
            "number": row.get("build_number"),
        },
        "model": {
            "name": meta.get("model_rel") or row.get("model_filename"),
            "path": row.get("model_filename") or meta.get("model_path"),
            "type": row.get("model_type"),
            "size": row.get("model_size"),
            "n_params": row.get("model_n_params"),
        },
        "config": {
            "n_prompt": row.get("n_prompt"),
            "n_gen": row.get("n_gen"),
            "n_depth": row.get("n_depth", 0),
            "n_batch": row.get("n_batch"),
            "n_ubatch": row.get("n_ubatch"),
            "n_threads": row.get("n_threads"),
            "n_gpu_layers": row.get("n_gpu_layers"),
            "flash_attn": row.get("flash_attn"),
            "type_k": row.get("type_k"),
            "type_v": row.get("type_v"),
            "reps": meta.get("reps"),
        },
        "test": test_kind(row),
        "metric": {
            "avg_ts": row.get("avg_ts"),
            "stddev_ts": row.get("stddev_ts"),
            "avg_ns": row.get("avg_ns"),
            "stddev_ns": row.get("stddev_ns"),
        },
    }


def collect():
    records = []
    if not os.path.isdir(RUNS_DIR):
        return records
    for fname in sorted(os.listdir(RUNS_DIR)):
        if not fname.endswith(".json") or fname.endswith(".meta.json"):
            continue
        path = os.path.join(RUNS_DIR, fname)
        mtime_iso = datetime.fromtimestamp(
            os.path.getmtime(path), tz=timezone.utc
        ).isoformat()
        try:
            with open(path) as fh:
                rows = json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"  [warn] skipping unreadable {fname}: {exc}", file=sys.stderr)
            continue
        if not isinstance(rows, list):
            rows = [rows]
        meta = load_meta(path)
        for row in rows:
            records.append(normalize(row, meta, mtime_iso))
    return records


def fmt_ts(rec):
    m = rec["metric"]
    if m.get("avg_ts") is None:
        return "-"
    sd = m.get("stddev_ts") or 0
    return f"{m['avg_ts']:.1f}±{sd:.1f}"


def write_summary(records):
    """Markdown table: rows = model x context x tag, columns = backend (pp / tg t/s)."""
    backends = sorted({r["backend"] for r in records if r.get("backend")})
    grid = defaultdict(lambda: defaultdict(dict))
    for r in records:
        mname = r["model"]["name"] or "?"
        ctx = r.get("context", "default")
        tag = r.get("tag") or ""
        grid[(mname, ctx, tag)][r.get("backend")][r["test"]] = fmt_ts(r)

    lines = []
    lines.append("# Strix Halo Benchmark Summary")
    lines.append("")
    lines.append(
        f"Generated {datetime.now(tz=timezone.utc).isoformat()} · "
        f"{len(records)} measurements · backends: {', '.join(backends) or 'none'}"
    )
    lines.append("")
    lines.append("Throughput in tokens/sec (avg±stddev). "
                 "**pp** = prompt processing, **tg** = token generation.")
    lines.append("")

    header = ["model", "context", "tag"]
    for b in backends:
        header += [f"{b} pp", f"{b} tg"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")

    for key in sorted(grid):
        mname, ctx, tag = key
        cells = grid[key]
        row = [mname, ctx, tag or "-"]
        for b in backends:
            row.append(cells.get(b, {}).get("pp", "-"))
            row.append(cells.get(b, {}).get("tg", "-"))
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    return "\n".join(lines) + "\n"


def main():
    records = collect()
    os.makedirs(RESULT_DIR, exist_ok=True)

    index_path = os.path.join(RESULT_DIR, "index.json")
    out = {
        "generated": datetime.now(tz=timezone.utc).isoformat(),
        "count": len(records),
        "records": records,
    }
    with open(index_path, "w") as fh:
        json.dump(out, fh, indent=2)

    summary_path = os.path.join(RESULT_DIR, "SUMMARY.md")
    with open(summary_path, "w") as fh:
        fh.write(write_summary(records))

    print(f"Wrote {index_path} ({len(records)} measurements)")
    print(f"Wrote {summary_path}")


if __name__ == "__main__":
    main()

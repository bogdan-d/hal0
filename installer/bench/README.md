# Strix Halo Benchmark Harness (hal0)

GPU inference benchmarking for hal0 / Strix Halo, sweeping **both runtimes — ROCm and
Vulkan** — with the official `llama-bench`, emitting structured JSON for Hal0 tracking.

Ported from
[`kyuz0/amd-strix-halo-toolboxes/benchmark`](https://github.com/kyuz0/amd-strix-halo-toolboxes/tree/main/benchmark),
adapted to drive the container images already in root's podman via `podman` (not `toolbox`).

## Layout & privilege model (D hardened-perms)

This harness is **root-owned and root-executed**. The unprivileged `hal0` agent never runs
it directly — it goes through the `hal0-benchctl` sudo seam, exactly like `hal0-slotctl`.

| Path | Owner | Purpose |
|------|-------|---------|
| `/usr/lib/hal0/bench/` | `root:root` | this harness (not agent-writable, off NFS) |
| `/usr/lib/hal0/bin/hal0-benchctl` | `root:root 0755` | the seam (validates args, execs harness) |
| `/etc/sudoers.d/hal0-benchctl` | `root:root 0440` | the grant |
| `/var/lib/hal0/benchmarks/` | `hal0:hal0` | results (`runs/`, `logs/`, `index.json`, `SUMMARY.md`) |

## Usage

Agents/operators use the seam:

```bash
S="sudo -n /usr/lib/hal0/bin/hal0-benchctl"
$S run --exclusive                 # full curated sweep, clean GPU
$S run-model <rel.gguf>            # one model, both backends
$S sweep <rel.gguf> <backend> -ub 512,1024,2048   # tuning (whitelisted flags)
$S aggregate                       # rebuild index.json + SUMMARY.md
$S list
```

Direct (root shell, e.g. operator on hal0) — the engine under the seam:

```bash
/usr/lib/hal0/bench/run_benchmarks.sh --help
/usr/lib/hal0/bench/run_benchmarks.sh --all-models --contexts all --exclusive
/usr/lib/hal0/bench/generate_results_json.py /var/lib/hal0/benchmarks
```

`run_benchmarks.sh` also accepts `--force` (run on a busy GPU; contended numbers) and
`--dry-run`; the seam deliberately does **not** expose `--force`.

## ⚠️ GPU contention

One iGPU, shared with the live inference slots. The harness refuses to run while a GPU slot
is active; `--exclusive` stops/restarts them for clean numbers (briefly offlines production).
`hal0-slot@npu` is GPU-free and ignored.

## Tuning / extending (operator, edits config.sh)

- Add a backend: entry in `BACKENDS` (`image|bench_bin|ubatch|env`) + `BACKEND_ORDER`.
- Add a context: entry in `CTX_CONFIGS` (`args|reps`, `%UB%` = per-backend ubatch).
- Curated default model set: `DEFAULT_MODELS`. Common flags: `COMMON_BENCH_ARGS`.

## Scope & roadmap

Now: the kyuz0 **toolbox sweep** (raw `llama-bench` across backends) + a tuning `sweep` verb.
Deferred: MTP/draft-speculative bench (server-level; see `/root/bench_mtp.py`), RPC bench
(needs ≥2 nodes), pi-bench (coding-agent eval). Upstream end-state: a `hal0 bench` CLI +
`/api/benchmarks` route reading `index.json`, landed in the hal0 git repo.

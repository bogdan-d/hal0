# hal0-benchctl seam — internals & layout

Benchmarking is a rootful GPU operation; the unprivileged `hal0` user reaches it only
through this seam, following hal0's D hardened-perms model (cf. `hal0-slotctl`,
`hal0-agentenv`).

## Components (installed)

| Path | Owner | Purpose |
|------|-------|---------|
| `/usr/lib/hal0/bin/hal0-benchctl` | `root:root 0755` | the seam — validates args, execs harness |
| `/etc/sudoers.d/hal0-benchctl` | `root:root 0440` | `hal0 ALL=(root) NOPASSWD: …/hal0-benchctl` |
| `/usr/lib/hal0/bench/` | `root:root` | harness (`run_benchmarks.sh`, `generate_results_json.py`, `config.sh`) — **not** agent-writable |
| `/var/lib/hal0/benchmarks/` | `hal0:hal0` | results (`runs/`, `logs/`, `index.json`, `SUMMARY.md`) |

The harness lives on a **local root-owned path** (not the `/mnt` NFS mount) precisely so
the agent can't tamper with a script that runs as root. Results are chowned back to
`hal0` after every run so the agent + UI can read them.

## Seam verbs & validation

- `run [--exclusive]` — curated sweep, all contexts.
- `run-model <rel.gguf> [--exclusive]` — one model, both backends.
- `sweep <rel.gguf> <backend> [--exclusive] <flags…>` — tuning; flags whitelisted.
- `aggregate` — rebuild `index.json` + `SUMMARY.md`.
- `list` — list result files.

Hardening:
- model path: no `..`, must match `^[A-Za-z0-9][A-Za-z0-9._/-]*\.gguf$`, must exist under `/mnt/ai-models`.
- backend: `rocm | vulkan_radv` only.
- sweep flags: only `-b -ub -ngl -fa -ctk -ctv -p -n -d -r -t -mmp -pg` with
  numeric/comma/quant values; `-m`, `-o`, and anything else are rejected.
- no shell evaluation; the harness execs `podman` with fixed device/mount flags.

## Sweep matrix (config.sh)

- Backends: `rocm` (bench bin `/usr/local/bin/llama-bench`, `-ub 2048`,
  `HSA_OVERRIDE_GFX_VERSION=11.5.1`, `GGML_HIP_ENABLE_UNIFIED_MEMORY=1`),
  `vulkan_radv` (`/usr/bin/llama-bench`, `-ub 512`).
- Contexts: `default` (pp512/tg128, r5), `ctx32k`, `ctx65k` (`-p 2048 -n 32 -d …`, r3).
- Common: `-ngl 99 -fa 1 -mmp 0`. Curated `DEFAULT_MODELS` one per size class.

## Revoke

```bash
sudo rm /etc/sudoers.d/hal0-benchctl     # removes the grant; harness stays, agent can't invoke it
```

## Upstreaming (future)

The "official Hal0 feature" end-state is a `hal0 bench` CLI subcommand + `/api/benchmarks`
route reading `index.json`, landed in the hal0 git repo (not edited into the packaged
`/usr/lib/hal0/current`, which is replaced on update). This seam is the bridge until then.

---
name: hal0-bench
category: homelab-ops
description: Running LLM inference benchmarks on hal0 / Strix Halo. Use when asked to benchmark a model, measure tokens/sec (prompt-processing or generation), compare the ROCm vs Vulkan backends, sweep context lengths, or refresh benchmark data. Encodes the structural fact that benchmarking is a rootful GPU op the unprivileged agent reaches ONLY through the hal0-benchctl sudo seam, and that the single iGPU is shared with the live inference slots.
---

# hal0 benchmarking

Benchmarks llama.cpp inference on this box across **both runtimes (ROCm and Vulkan)**
using the official `llama-bench`, and writes structured JSON for Hal0 tracking.

You (the `hal0` agent user) are unprivileged. Benchmark containers are **rootful** and
need `/dev/kfd` + root's podman image store, so you drive everything through the
**`hal0-benchctl` sudo seam** — the same hardened-seam pattern as `hal0-slotctl`. Never
call `podman`/`systemctl` directly; you don't have rights and shouldn't.

```bash
sudo -n /usr/lib/hal0/bin/hal0-benchctl <command>
```

- **Engine** (root-owned, you cannot edit): `/usr/lib/hal0/bench/`
- **Results** (yours to read): `/var/lib/hal0/benchmarks/` → `SUMMARY.md`, `index.json`, `runs/`
- **Backends:** `rocm` (`ghcr.io/hal0ai/amd-strix-halo-toolboxes:rocm-7.2.4-rocmfp4-server`),
  `vulkan_radv` (`…:vulkan-radv-server`) — images already in root's podman.

## When to use this skill

- "Benchmark <model>" / "ROCm vs Vulkan speed?" / "measure tg or pp t/s".
- Refresh the dataset after a new model/quant/image.
- As the measurement engine for the [`hal0-tune`](../hal0-tune/SKILL.md) skill.

## Commands (via the seam)

```bash
S="sudo -n /usr/lib/hal0/bin/hal0-benchctl"

$S list                                            # what results exist
$S run-model qwen3.5-0.8b/Qwen3.5-0.8B-UD-Q4_K_XL.gguf   # one model, both backends, all ctx
$S run                                             # full curated sweep (config.sh DEFAULT_MODELS)
$S run --exclusive                                 # clean numbers (see GPU rule below)
$S aggregate                                       # rebuild index.json + SUMMARY.md
$S help
```

Model paths are relative to `/mnt/ai-models` and validated by the seam (must exist, end
in `.gguf`, no traversal). Runs are **resumable** — an existing result cell is skipped.

## ⚠️ The GPU rule (most important)

There is **one iGPU**, shared with the live inference slots (`hal0-slot@agent`,
`@nano`, …). Benchmarking a busy GPU gives meaningless numbers, so the harness
**refuses to run while any GPU slot is active**:

```
[abort] GPU inference slots are active; results would be skewed: ...
```

- For **authoritative numbers**: add `--exclusive` — it stops the GPU slots, runs, and
  restarts them on exit. This briefly takes production inference offline, so only do it
  when nothing is mid-request, and afterwards confirm recovery:
  `hal0 slot status` (or `systemctl is-active hal0-slot@agent`).
- There is no `--force` via the seam by design: the agent must not silently publish
  contended results.
- `hal0-slot@npu` does not use the GPU and is ignored.

## Reading results

- `SUMMARY.md` — model × context × tag, pp/tg t/s per backend. Read first.
- `index.json` — `{generated, count, records[]}`; each record has `backend`, `gpu`,
  `llamacpp_build`, `model{name,size,type}`, `config{n_prompt,n_gen,n_depth,n_batch,
  n_ubatch,n_gpu_layers,flash_attn,type_k,type_v}`, `test` (`pp`/`tg`), `metric{avg_ts,stddev_ts}`.
- A `runs/<cell>.json.failed` + `logs/<cell>.log` means that cell errored (usually OOM on
  a big model, or a GPU hang). Read the log; don't report that cell.

**Sanity gate:** a real GPU run shows `backend`=`rocm`/`vulkan_radv` and `gpu` naming the
Radeon 8060S. CPU-low t/s with a blank GPU means the run was wrong — don't report it.

## How this fits hal0 (D hardened-perms)

The seam `/usr/lib/hal0/bin/hal0-benchctl` is the entire privileged surface: it validates
the model path, backend, and (for tuning) a llama-bench flag whitelist, then execs the
root-owned harness — no shell, no arbitrary args. Grant:
`/etc/sudoers.d/hal0-benchctl`. See `references/seam.md` for internals and the model
sweep matrix. To extend the curated models/contexts, an operator edits
`/usr/lib/hal0/bench/config.sh` (root).

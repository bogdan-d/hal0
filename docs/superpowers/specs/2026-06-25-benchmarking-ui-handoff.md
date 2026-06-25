# Handoff: Benchmarking Toolbox → Dashboard/UI feature plan

**Audience:** `claude-design` (dashboard/UX) + whoever builds the `/api/benchmarks` backend.
**Status:** the *engine* (harness + privileged seam + result schema) is built, merged (#967), and verified on CT105. **There is no API surface and no UI yet** — this doc specifies what to build and every integration point it must respect.
**Author context:** written from the implementation session that shipped the toolbox. Read it end to end before designing; the GPU-contention and job-lifecycle sections are load-bearing.

---

## 1. TL;DR — what exists vs what you're designing

**Exists today (the engine):**
- A llama.cpp benchmark harness at `/usr/lib/hal0/bench/` (root-owned): `run_benchmarks.sh`, `config.sh`, `generate_results_json.py`.
- A hardened privileged seam `/usr/lib/hal0/bin/hal0-benchctl` (+ `/etc/sudoers.d/hal0-benchctl`) — the **only** way the unprivileged `hal0` user runs rootful GPU benchmarks.
- Results at `/var/lib/hal0/benchmarks/` (`hal0:hal0`, agent-readable): `runs/*.json` (+ `.meta.json`), `logs/*.log`, `index.json` (normalized aggregate), `SUMMARY.md`.
- Two bundled agent skills, `hal0-bench` (run) and `hal0-tune` (benchmark-driven flag tuning).

**You're designing:**
1. A **`/api/benchmarks/*`** backend surface (the dashboard can't `sudo` from the browser — it must go through `hal0-api`, which calls the seam).
2. A **Benchmarks UI** (run/queue/monitor/compare), plus **entry points from model cards and profile cards**.
3. **Integration** with the model registry, the profiles/slots tuning loop, and the existing auto-generated **Model Roster** doc.

> ⚠️ The backend API is a **prerequisite** — none of the UI works until `/api/benchmarks` exists. Treat it as part of this feature, not a given.

---

## 2. Architecture & trust boundary (don't fight this)

```
Browser (dashboard)
   │  fetch /api/benchmarks/*
   ▼
hal0-api  (runs as the UNPRIVILEGED `hal0` user)
   │  subprocess.run(["sudo","-n","/usr/lib/hal0/bin/hal0-benchctl", verb, ...])
   ▼  (D hardened-perms — the seam is the entire privileged surface)
hal0-benchctl  (root; validates model path + backend + flag whitelist; no shell)
   │  execs
   ▼
run_benchmarks.sh → podman run --entrypoint llama-bench (rootful container, /dev/kfd)
   │  writes
   ▼
/var/lib/hal0/benchmarks/{runs,logs}/…  →  generate_results_json.py  →  index.json + SUMMARY.md
   ▲
hal0-api reads index.json  →  serves /api/benchmarks/results  →  UI
```

Key invariants the design must preserve:
- **Browser never touches podman/sudo.** Everything funnels through `hal0-api` → the seam. The seam **validates and whitelists** (model path under `/mnt/ai-models`, backend ∈ `{rocm, vulkan_radv}`, tuning flags ∈ a fixed list). The API must not try to bypass it.
- **The API runs as `hal0`** and already has the `sudo -n <seam>` pattern to copy: see `src/hal0/agents/hermes_provision.py::_privileged_env_write` (`subprocess.run(["sudo","-n",_HAL0_AGENTENV, verb, name], ...)`). Mirror it for `hal0-benchctl`.
- **One physical iGPU.** Benchmarks are **mutually exclusive with each other and with live serving**. See §7.

---

## 3. Data contract — what the UI reads

### 3.1 `GET /api/benchmarks/results` ← `/var/lib/hal0/benchmarks/index.json`
`index.json` = `{ generated, count, records[] }`. Each **record** (one llama-bench test row, normalized):

| Field | Type | Notes / UI use |
|---|---|---|
| `timestamp` | ISO8601 | when the cell ran |
| `host` | str | `hal0` |
| `gpu` | str | `Radeon 8060S (gfx1151)` |
| `backend` | `rocm` \| `vulkan_radv` | **the ROCm-vs-Vulkan axis** |
| `runtime_image` | str | toolbox image ref (provenance) |
| `context` | `default` \| `ctx32k` \| `ctx65k` | depth bucket |
| `tag` | str | `""` for baseline, `sweep` for tuning runs |
| `llamacpp_build` | `{commit, number}` | **results are build-specific — show it; invalidate on change** |
| `model` | `{name, path, type, size, n_params}` | `name` = registry-relative path; `size` bytes; `type` = quant/arch string from gguf |
| `config` | `{n_prompt, n_gen, n_depth, n_batch, n_ubatch, n_threads, n_gpu_layers, flash_attn, type_k, type_v, reps}` | the exact run params — **the sweep axes for tuning** |
| `test` | `pp` \| `tg` | **pp** = prompt processing (prefill), **tg** = token generation (decode) |
| `metric` | `{avg_ts, stddev_ts, avg_ns, stddev_ns}` | `avg_ts` = tokens/sec; show `±stddev_ts` |

One "benchmark of a model on a backend at a context" usually yields **2 records** (pp + tg). A tuning **sweep** (comma-value lists, e.g. `-ub 512,1024,2048`) yields **one record per parameter combination × {pp,tg}** — that's the dataset for a parameter-vs-throughput chart.

### 3.2 `SUMMARY.md` — pre-rendered ROCm-vs-Vulkan table (model × context × tag, pp/tg per backend). Useful as a fallback/export; prefer `index.json` for interactive UI.

### 3.3 Failure & quality signals (must surface, don't hide)
- A cell that errored leaves `runs/<cell>.json.failed` + `logs/<cell>.log` and **no record** in `index.json`. The API should expose failed cells + the tail of the log (common causes: **OOM** on large models, **GPU hang**, missing gguf).
- **Contended numbers:** if a run was forced onto a busy GPU (see §7), it must be labeled non-authoritative. (Today the seam refuses busy-GPU runs; if you add a "force" path, you own the labeling.)
- **Sanity gate:** a real GPU run has `backend` set and `gpu` naming the 8060S; CPU-fallback (blank/low) must be flagged, never charted as truth.

---

## 4. Control surface — what the UI triggers (and the API it needs)

The seam verbs (the raw capability):

| Verb | Args | Meaning |
|---|---|---|
| `run` | `[--exclusive]` | full curated sweep (config.sh `DEFAULT_MODELS`, all contexts) |
| `run-model` | `<rel.gguf> [--exclusive]` | one model, both backends, all contexts |
| `sweep` | `<rel.gguf> <backend> [--exclusive] <flags…>` | tuning; flags whitelisted: `-b -ub -ngl -fa -ctk -ctv -p -n -d -r -t -mmp -pg` (comma value lists allowed) |
| `aggregate` | — | rebuild `index.json` + `SUMMARY.md` |
| `list` | — | list result files |

**Required new backend endpoints** (strawman — design against these, mirror the pull-job lifecycle in `routes/models.py`):

```
POST   /api/benchmarks/run            → 202 {job_id}      # body: {kind: "model"|"sweep"|"curated", model_id?, backends?, contexts?, reps?, exclusive?, sweep?:{flags...}, tag?}
GET    /api/benchmarks/jobs/{id}      → {state, progress, current_cell, eta, log_tail}
GET    /api/benchmarks/jobs/{id}/stream  (SSE: queued → running(cell x/N) → aggregating → completed|failed)
POST   /api/benchmarks/jobs/{id}/cancel
GET    /api/benchmarks/results        → index.json (filter by model/backend/context/tag/build)
GET    /api/benchmarks/results/{model_id}  → records for one model (for model-card badges)
GET    /api/benchmarks/preflight      → {gpu_busy, serving_slots:[…], seam_installed, last_run}   # drives the run dialog
```

**Job lifecycle is the crux:** a benchmark is **long-running** — a single 35B model is minutes; `--all-models --contexts all` or a wide sweep is **tens of minutes to hours**. So:
- Async job + **SSE progress** (reuse the exact shape of `GET /api/models/{id}/pull/stream`).
- **Serialize** — only one benchmark job at a time (one GPU). A queue with cancel.
- Resumable: the harness **skips cells whose result already exists**. Surface "cached vs fresh" so users understand why a re-run is instant.
- Persist job state across dashboard reloads (mirror `/pull/status`).

---

## 5. Settings & configuration surface (what the UI exposes)

Split clearly into **per-run (UI)** vs **host config (operator-only, `config.sh`)**.

**Per-run (the run dialog):**
| Setting | Options | Default | Maps to |
|---|---|---|---|
| Model(s) | pick from registry (§6) or curated set | curated | `run-model` / `run` |
| Backends | ROCm, Vulkan, both | both | `--backends` |
| Contexts | default (pp512/tg128), 32K, 65K | default | `--contexts` |
| Reps | 1–10 | 5 (def) / 3 (long) | `--reps` |
| GPU mode | **Refuse if busy** (safe) · **Exclusive** (stop slots) | refuse | `--exclusive` (see §7) |
| Tag | string | `sweep` for tuning | `--tag` |

**Tuning sweep (advanced / hal0-tune surface):** value-list inputs for the whitelisted flags — `-ub`, `-b`, `-fa (0/1)`, `-ctk/-ctv (q8_0/f16/…)`, `-t`, `-p/-n/-d`. Render as multi-value chips → one chart axis each. Show the **Strix Halo priors** as defaults/hints (ROCm likes `-ub 2048`, Vulkan `-ub 512`; `q8_0` KV ≈ big memory save, small quality cost). Enforce the whitelist client-side and re-validate server-side (the seam rejects anything else).

**Host config (read-only in UI, link to "edit via operator"):** the backend→image map, bench-bin paths, common flags (`-ngl 99 -fa 1 -mmp 0`), curated `DEFAULT_MODELS`, context definitions — all in `/usr/lib/hal0/bench/config.sh`. Don't build UI to edit these; do surface their current values (provenance).

---

## 6. Integration with hal0 model listings (registry)

- The model list comes from **`GET /api/models`** (UI `useModels`, `routes/models.py`). A `Model` has `id, longName, repo, params, size, labels, type, device, backends[], installed, runtime`; the registry row also has the **gguf `path`** and `defaults`.
- **Path mapping (important):** the seam takes a path **relative to `/mnt/ai-models`** and validates it (`^[A-Za-z0-9][…]\.gguf$`, no `..`, must exist). The registry stores **absolute** gguf paths. The API must strip the `/mnt/ai-models/` prefix and reject anything outside the store. Sharded models → first shard (`*-00001-of-*.gguf`).
- **`backends[]` drives which runtimes to offer/sweep** for that model (don't offer Vulkan-only models a ROCm run, etc.).
- **Close the loop on model cards:** show each model's latest pp/tg per backend as a badge ("ROCm 46 · Vulkan 53 tg t/s"), with a **"Benchmark"** action that opens the run dialog pre-scoped to that model. `GET /api/benchmarks/results/{model_id}`.
- **Feed the existing Model Roster** (see §9) instead of reinventing a table.

---

## 7. GPU contention & exclusive mode — the #1 UX safety concern

There is **one iGPU**, shared with live inference slots (`hal0-slot@agent`, `@nano`, …). Benchmarking a busy GPU = garbage numbers, so:

- The harness **refuses** to run while any GPU slot is active (NPU slot is GPU-free, ignored).
- `--exclusive` **stops the GPU slots, runs, restarts them on exit** — i.e. it **takes production inference offline** for the duration.

The UI **must**:
1. Call `GET /api/benchmarks/preflight` and **show which slots are serving** before any run.
2. Default to **"refuse if busy"**; make **Exclusive** a deliberate, confirmed choice with a clear warning ("This stops these slots: agent, nano — inference will be unavailable for ~N min").
3. Show **live progress + ETA** during exclusive runs and **confirm slots restarted** afterward (and on cancel/error — the harness restores via a trap, but verify and surface it).
4. Never silently produce contended numbers. There is intentionally **no browser-exposed `--force`**.

---

## 8. Integration with profiles/slots — the tuning loop (hal0-tune)

Tuning isn't just measuring — it's **finding better flags and applying them**. The apply target is the **profile/slot** model:
- A slot = **device** (`gpu-rocm`/`gpu-vulkan`) + **provider** (`llama-server`) + **profile** (container image + **bench-tuned flags**). Profiles live in `/etc/hal0/profiles.toml`, surfaced via **`GET /api/profiles`** (seed set: `rocm`, `rocm-dnse`, `rocm-moe`, `vulkan`). GPU profiles carry an authoritative **`backend`** field (`rocm`/`vulkan`).
- **Design a "tune → apply" flow:** hal0-tune produces a winning flag set (e.g. `-ub 2048 -ctk q8_0`); the UI should let the user **write it back to a profile** (new profile or override) or a **slot's TOML**, then reload the slot (the platform regenerates the unit via its seam). This is a **production change** — gate it, back up, verify slot health after, offer rollback.
- Profile cards already display bench metrics (per `providers-profiles-devices.mdx`) — wire those to real `index.json` data.

---

## 9. Integration with the existing Model Roster (don't reinvent)

`docs/reference/model-roster-benchmark.mdx` already renders a head-to-head roster via `components/ModelRoster.astro` + `data/model-roster.ts` (+ `ROSTER_DATE`), "auto-generated… whenever the roster is re-benchmarked." **This is the natural consumer of our `index.json`.**
- **Reconcile two data sources (call this out explicitly to design):**
  - **Our harness** = `llama-bench` → synthetic **pp/tg** across **backends × contexts × sweeps**. Great for ROCm-vs-Vulkan, context curves, flag tuning. **Cannot** produce **MTP acceptance %** (MTP/draft is a `llama-server` feature, not `llama-bench`).
  - **The roster** = `llama-server` `/completion` timings → served **decode/prefill/MTP-acc**, uniform exclusive sweep. Closer to "what a slot delivers."
  - Don't conflate them. Either keep two views ("synthetic vs served") or extend the toolbox with a server-side bench (future — see §12) to unify. The UI should label which methodology produced a number.

---

## 10. Telemetry to reuse / contrast (live vs measured)

Distinguish **live serving telemetry** from **controlled benchmarks**:
- `GET /api/stats/throughput/history` — rolling live tps per slot (already drives the dashboard). TTFT infra exists (`app.state.ttft_events`, `slots/ttft_samples.py`); hardware stats at `/api/stats/hardware` (powers the new iGPU gauge).
- Reusable UI atoms already in the dash: the **iGPU gauge** (`inference-pane.jsx`), the **throughput sparkline** (`TpTile`/`SparkBars`). Reuse the visual language for benchmark charts so it feels native.
- Benchmark results are **point-in-time measurements**, not a live stream — design them as a comparison/history surface, not a gauge.

---

## 11. States & edge cases the design must handle

- **Empty** (no results yet) → first-run CTA to benchmark the curated set or a model.
- **Running** → progress per cell (x/N), current model/backend/context, ETA, cancel.
- **Failed cell** → badge + log tail; OOM on big models is common and expected.
- **GPU busy / refused** → explain + offer Exclusive (with the §7 warning).
- **Stale results** → results are tied to `llamacpp_build.commit`, image, and the gguf. If the model's quant/file changed or llama.cpp was rebuilt, mark old numbers stale (don't compare across builds silently).
- **Backend not supported by model** → don't offer it.
- **Concurrency** → only one job runs (one GPU); others queue.
- **Seam/permission missing** → if `hal0-benchctl`/sudoers isn't installed (e.g. dev host), `preflight` returns `seam_installed:false` → disable run UI with an explanation.
- **Large-model time/cost** → show time estimates; `--all-models --contexts all` can run for hours.
- **Cached vs fresh** → resumable runs skip existing cells; make that visible.

---

## 12. Scope boundaries & "what's deliberately not here"

- **MTP/draft acceptance** — not producible by `llama-bench`; needs a server-side bench (hal0 already has `/root/bench_mtp.py` as prior art). Future toolbox extension if you want unified served metrics.
- **RPC / multi-node** — out of scope (needs ≥2 Strix Halo nodes).
- **pi-bench (coding-agent eval)** — a separate stack (SWE-bench, LLM judge) deferred entirely; not part of this toolbox.

---

## 13. Things the requester may have under-specified (read this)

A punch-list of non-obvious facts the design should bake in:
1. **Backend API is mandatory and non-trivial** — the job runner + SSE + seam invocation + result reading is the bulk of the work; the UI is the easy half.
2. **Deploy/caching gotcha (now fixed, #969):** the dashboard `index.html` is served `no-cache` and `deploy.sh` installs to the served dist — but only after a real deploy. If "I can't see my change on 105," it's stale HTML/dist, not your code. (Don't add a service worker — there isn't one.)
3. **Result ownership:** results are written by root then `chown`ed to `hal0`; world/group-readable, so `hal0-api` can read `index.json` directly. No special perms needed to *read*; *running* needs the seam.
4. **Path semantics:** registry uses absolute gguf paths; the seam wants **relative-under-`/mnt/ai-models`**. The API owns the mapping + validation. Sharded → first shard.
5. **`backend` is the authoritative ROCm/Vulkan axis** (profiles, results), not the profile slug or `device` string.
6. **Results are build/image/quant-specific.** Always show `llamacpp_build` + image; invalidate comparisons across them.
7. **Two benchmark methodologies** exist (synthetic `llama-bench` vs served roster) — label them; don't average them together.
8. **Exclusive mode = production downtime.** This is the highest-risk action in the feature; design the confirmation, progress, and restore-verification carefully.
9. **Strix Halo specifics** are pre-baked (gfx1151, `HSA_OVERRIDE_GFX_VERSION=11.5.1`, unified memory, per-backend `-ub`). Surface them as read-only provenance; don't ask users to set them.
10. **Where benchmarking should live in the IA:** a top-level **Benchmarks** page (history + run + compare), plus **"Benchmark"** on model cards and **"Tune"** on profile cards, plus feeding the docs **Model Roster**. Decide whether tuning is its own surface or an advanced mode of Benchmarks.
11. **Units:** tokens/sec (pp/tg), ms (TTFT), GiB (size), %, MHz/°C (gauge). Be consistent; show ± stddev.
12. **Authz:** decide who can trigger benchmarks (esp. exclusive) — it's a privileged, GPU-monopolizing, production-affecting action.

---

## 14. Suggested deliverables back from claude-design
1. IA + flows for: **Benchmarks page**, **run dialog** (with the §7 exclusive flow), **results/compare views** (ROCm-vs-Vulkan, context curves, sweep parameter charts), **tuning → apply-to-profile** flow.
2. Model-card + profile-card integrations.
3. The `/api/benchmarks/*` contract finalized against §4 (so backend + UI can build in parallel).
4. Empty/running/failed/stale/refused states (§11).

**Reference files:** harness `/usr/lib/hal0/bench/`; seam `installer/wrappers/hal0-benchctl` + `packaging/sudoers/hal0-benchctl`; result schema `installer/bench/generate_results_json.py`; skills `installer/agent-skills/{hal0-bench,hal0-tune}/SKILL.md`; registry `src/hal0/api/routes/models.py`; profiles `docs/reference/providers-profiles-devices.mdx`; roster `docs/reference/model-roster-benchmark.mdx` + `components/ModelRoster.astro`; seam-call pattern `src/hal0/agents/hermes_provision.py::_privileged_env_write`; pull-job lifecycle `routes/models.py` (`/pull`, `/pull/stream`, `/pull/cancel`).

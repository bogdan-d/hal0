# hal0 — v1 Plan

A polished, reliable, open-source home AI inference platform. Forked from
the existing haloai project; stripped to a tight core (slot + model
management, OpenAI-compatible API, polished dashboard, prewired chat UI,
one-line install) and re-architected around the things that make hal0
different from "a wrapper around llama-server": hardware-aware slots,
clean lifecycle, and a real reliability bar.

Target launch: **hal0 v1.0** — Strix Halo + AMD GPU + NVIDIA GPU Linux
home installs, OpenAI-compatible inference, bundled OpenWebUI chat.

---

## 1. Scope

### v1 ships

- **Core inference platform**
  - OpenAI-compatible API (`/v1/chat/completions`, `/v1/embeddings`,
    `/v1/rerankings`, `/v1/audio/transcriptions`, `/v1/audio/speech`,
    `/v1/models`)
  - Slot lifecycle (load / unload / restart / swap / spawn / terminate)
    on `hal0-slot@.service` template units
  - Model registry, downloads, assignment to slots
  - Dispatcher: registry-aware routing with cold-cache prefetch and
    upstream fallback
  - Provider abstraction with **four** providers in v1:
    - `llama.cpp` (Vulkan default, ROCm opt-in) — chat / embed / rerank / vision
    - `flm` (AMD NPU, optional) — chat / embed / ASR multiplex
    - `moonshine` (STT) — CPU/Vulkan, OpenAI-compatible
    - `kokoro` (TTS) — CPU/Vulkan
  - External-LLM upstreams (OpenRouter, Anthropic, OpenAI, custom
    OpenAI-compatible)
- **Dashboard UI** (Vue 3 + Pinia + Tailwind 4)
  - 9 views: Dashboard, Slots, Models, Hardware, Logs, Settings,
    Providers, FirstRun, plus a not-found / error shell
  - Dark mode only; mobile-responsive on read-only paths
  - SSE for slot status + log tail
  - Hardware-aware slot config form (VRAM fit warnings inline)
- **Bundled prewired OpenWebUI** at `:3001`
  - Installer pre-configures `OPENAI_API_BASE_URLS=http://127.0.0.1:8080/v1`
  - `WEBUI_AUTH=False` (LAN-only home install)
  - State at `/var/lib/hal0/openwebui/`
- **One-line installer**
  - Sensible defaults, non-interactive (`curl -fsSL hal0.dev/install | bash`)
  - Pre-flight checks, hardware probe, lay down `/etc/hal0/slots/{primary,embed,stt,tts}.toml`
  - Pulls toolbox images in background
  - First-run wizard in dashboard for default-model pick
- **Self-update**
  - `hal0 update` — atomic version swap with rollback
  - Stable + nightly channels
  - Slot units keep running across API restart
- **Reliability (Tier 1 + 2 + 3 from audit)**
  - Atomic env writes, schema-validated TOML, structured error codes
  - Tightened health probes, tuned cold-boot timeouts
  - **Slot lifecycle state machine** (offline → pulling → starting → warming → ready → serving → idle → unloading)
  - **Request coalescing / single-flight** on cold-cache prefetch
  - **Config evolution / migration tooling**
  - Dispatcher decision logging with structured breadcrumbs
- **Tests**
  - Unit tests per module (pytest)
  - Slot integration tests on CI (real `hal0-slot@.service` with Qwen3 0.5B on Vulkan-CPU)
  - Playwright γ tests on every critical UI path

### v0.2 (deferred)

- Memory subsystem
- MCP support
- Kyuzo image generation (ComfyUI provider)
- Benchmarks UI + Presets UI
- AUR PKGBUILD + Ubuntu PPA
- Caddy reverse proxy + auth + `hal0.local` mDNS
- Light mode toggle

### Strip (gone for good unless re-justified)

Agents subsystem, training subsystem, clawteam (multi-agent), kanban,
voice gateway (the Hermes voice pipeline; provider slots are kept),
vault, notes, projects, skills, fixlog, reflection, RAG, ChatOps
adapters, all extension-bundled services other than OpenWebUI, vLLM,
Vibevoice, Whisper.cpp, Infinity.

---

## 2. Architecture

### Deployment model

Linux host + systemd. The hal0 API runs as `hal0-api.service`. Each slot
is an instance of the `hal0-slot@.service` template unit, parameterized
by slot name. Each slot's `ExecStart` is `docker run` against a toolbox
image (`hal0-toolbox-vulkan`, `hal0-toolbox-rocm`, or the FLM/Moonshine/
Kokoro images). OpenWebUI is its own systemd unit running its official
container.

```
systemd
├── hal0-api.service           (FastAPI on :8080, host process)
├── hal0-openwebui.service     (docker run open-webui, host :3001)
└── hal0-slot@.service         (template)
    ├── hal0-slot@primary
    ├── hal0-slot@embed
    ├── hal0-slot@stt
    └── hal0-slot@tts
```

### Filesystem layout (FHS-aligned)

```
/usr/lib/hal0/                  # code (versioned)
  current -> /usr/lib/hal0-0.1.0/   (symlink, atomic update target)
  hal0-0.1.0/
    bin/hal0                    # CLI + daemon entry (single binary)
    site-packages/hal0/         # python package
    ui/                         # built Vue dist
    systemd/                    # unit templates
    manifest.json               # toolbox image versions, etc.

/etc/hal0/                      # user-editable config (preserved on update)
  hal0.toml                     # top-level
  slots/
    primary.toml
    embed.toml
    stt.toml
    tts.toml
  providers.toml
  upstreams.toml
  hardware.json                 # written by hal0 probe; user can edit

/var/lib/hal0/                  # mutable state (preserved on update)
  models/                       # local model cache (or symlink to /mnt/...)
  registry/                     # model metadata, atomic TOML
  openwebui/                    # webui.db, uploads, vector_db, cache
  slots/<name>/                 # per-slot working dir
  hal0.previous/                # last installed version (for rollback)

/var/log/hal0/                  # optional (journald is primary)
```

`HAL0_HOME` env var overrides all the above for dev installs.

### Ports

- `8080` — hal0 API (dashboard + `/v1/*` + `/api/*`)
- `3001` — OpenWebUI (separate systemd unit)
- `8081-8099` — slot ports (assigned by `lib/config.next_free_port()`)

All slot ports bind `127.0.0.1` only; only the API and OpenWebUI bind
public interfaces.

### Naming

- Python package: `hal0`
- CLI binary: `hal0` (with subcommands)
- systemd prefix: `hal0-`
- Toolbox image org: `ghcr.io/hal0-dev/`

---

## 3. Module port plan

Modules ported from `/opt/haloai/lib/` (post-audit, zero coupling to
bloat — clean ports):

| haloai source | hal0 destination | Notes |
|---|---|---|
| `lib/slots.py` (1082) | `hal0/slots/manager.py` | Refactor for state machine (Tier 3) |
| `lib/dispatcher.py` (617) | `hal0/dispatcher/router.py` | Add single-flight + decision logging |
| `lib/proxy.py` | `hal0/dispatcher/proxy.py` | Keep for now; absorbed into router post-v0.2 |
| `lib/registry.py` | `hal0/registry/` (split: store + watcher) | Atomic TOML, mtime cache |
| `lib/capacity.py` | `hal0/slots/capacity.py` | Capacity snapshot |
| `lib/slot_unit_template.py` | `hal0/slots/unit_template.py` | Rendered for template unit, not per-slot units |
| `lib/providers/base.py` | `hal0/providers/base.py` | Provider ABC |
| `lib/providers/llama_server.py` | `hal0/providers/llama_server.py` | Kept |
| `lib/providers/flm.py` | `hal0/providers/flm.py` | Kept |
| `lib/providers/comfyui.py` | DROP (v0.2 image gen) | — |
| `lib/providers/vllm.py` | DROP (v0.2 perf path) | — |
| `lib/providers/test_providers.py` | `tests/providers/` | Migrate to pytest |
| `lib/hardware.py` | `hal0/hardware/` (split: probe + stats) | Adds `probe` CLI subcommand |
| `lib/upstreams.py` (737) | `hal0/upstreams/` | Adds adaptive cold-boot timeout |
| `lib/integrations.py` | `hal0/upstreams/integrations.py` | Provider catalog |
| `lib/config.py` (420) | `hal0/config/` (split: schema + loader) | Pydantic models, validation at load |
| `lib/env_manager.py` | `hal0/config/env.py` | Atomic env file writes |
| `lib/features.py` | `hal0/config/features.py` | Feature flag store |
| `lib/updater.py` (569) | `hal0/updater/` | Self-update logic |
| `lib/healthcheck.py` (409) | `hal0/health/` | System health endpoint |
| `lib/benchmark.py` (503) | DROP (v0.2 Benchmarks UI) | — |
| `lib/paths.py` | `hal0/config/paths.py` | FHS-aware path resolution + `HAL0_HOME` |

New modules (not in haloai):

- `hal0/installer/` — first-run + dashboard wizard backend, hardware probe writer
- `hal0/cli/` — `hal0` CLI entry (Click or Typer)
- `hal0/openwebui/` — companion service config writer
- `hal0/voice/` — Moonshine + Kokoro provider integration (the inference
  pieces of `lib/voice/`, not the Hermes voice gateway)

---

## 4. API decomposition

`api.py` (3697 lines) → `hal0/api/` with one APIRouter per module:

```
hal0/api/
  __init__.py            # FastAPI app factory
  deps.py                # Depends() helpers (slot manager, registry, etc.)
  routes/
    v1.py                # /v1/* (OpenAI-compat: chat, embeddings, rerank, audio)
    slots.py             # /api/slots/*
    models.py            # /api/models/*
    hardware.py          # /api/hardware, /api/stats/*
    logs.py              # /api/logs/*
    settings.py          # /api/settings/*
    health.py            # /api/health/*, /api/metrics, /api/status, /api/features
    providers.py         # /api/providers/*, /api/upstreams/*
    config.py            # /api/config/urls
    updater.py           # /api/updates/*
    installer.py         # /api/install/* (first-run wizard endpoints)
  middleware/
    error_codes.py       # structured error envelope
    request_id.py        # X-Request-ID
    cors.py
```

Routes dropped entirely: `/api/training/*`, `/api/agents/*`, `/api/kanban/*`,
`/api/rag/*`, `/api/voice/*` (the Hermes voice gateway — providers stay),
`/api/projects/*`, `/api/skills/*`, `/api/fixlog/*`, `/api/extensions/*`,
`/api/credentials/*` (defer to v0.2 with auth), `/api/auth/*` (defer),
`/api/mcp/*` (defer to v0.2), `/api/npu/pull` (folded into `/api/models`),
`/api/benchmark/*` (defer), `/api/presets/*` (defer).

---

## 5. Reliability work (Tier 1 + 2 + 3)

Concrete items, with file:line references against the haloai source as
the starting point.

### Tier 1 — bug fixes / hardening (audit-identified)

- `lib/upstreams.py:500-520` — cold-boot health probe 2s timeout. Replace
  with adaptive policy: probe interval `(0.5s, 1s, 2s, 5s, 10s)`
  exponential backoff with jitter, total grace `180s` per slot, exposed
  via `hardware.json` per-slot override
- `lib/slots.py:551-622` — non-atomic env writes. Use
  `tempfile.NamedTemporaryFile(delete=False, dir=...)` + `os.replace()`.
  Failure leaves prior env intact
- `lib/slots.py:899-920` — FLM/vLLM health probe accepts empty
  `/v1/models`. Require non-empty plus a `/v1/chat/completions` with
  `max_tokens=1` against a sentinel message before reporting `ready`
- `lib/slots.py:59-69`, `lib/dispatcher.py:115-120, 291`,
  `lib/capacity.py:85-110` — silent exception swallows. Replace with:
  log at WARN with structured fields, return typed error to caller,
  never `return {}` on parse failure
- New: pydantic-validated TOML schema at load time. Module
  `hal0/config/schema.py` defines `SlotConfig`, `ModelConfig`,
  `ProvidersConfig`, `UpstreamsConfig`. `lib/config.load_*()` returns
  validated models. Typos in `[slot] backend = vukan` raise at startup
  with the field path
- Structured error envelope on every API response:
  ```json
  {"error": {"code": "slot.not_ready", "message": "...", "details": {...}}}
  ```
  Error code namespace: `slot.*`, `model.*`, `dispatch.*`, `config.*`, `system.*`

### Tier 2 — polish

- `lib/dispatcher.py:217-237` — cold-cache prefetch timeout. Replace
  hardcoded 4s with `dispatcher.prefetch_timeout_s` config (default 8s)
  plus per-upstream parallel cap (default 4)
- `lib/slots.py:240-346` — negative tps math. Clamp at 0, log WARN when
  histogram counter resets detected
- `lib/slots.py:316-346` — `_drm_mem()` parser. Handle multi-line
  fdinfo, return `Optional[float]` instead of 0.0 on parse failure;
  call sites distinguish "unknown" from "zero"
- Dispatcher decision logging — every routing decision emits one
  structured log line: `{request_id, model, resolution_path, upstream,
  cache_state, latency_ms}`. Goes to journald with `SYSLOG_IDENTIFIER=hal0-dispatch`

### Tier 3 — architecture refactors

- **Slot lifecycle state machine.** `hal0/slots/state.py` defines:
  ```
  offline → pulling → starting → warming → ready
                                         ↓
                                       serving ↔ idle → unloading → offline
                                         ↓
                                       error
  ```
  State transitions are atomic, persisted to `/var/lib/hal0/slots/<name>/state.json`,
  and streamable via SSE. Dashboard surfaces real transitions, not just
  systemd snapshots
- **Request coalescing / single-flight.** `hal0/dispatcher/single_flight.py` —
  in-flight map keyed by `(upstream, operation)`. Concurrent identical
  prefetches share one HTTP call. Result propagated to all waiters. On
  error, all waiters get the same error (no retry storm)
- **Config migration tooling.** `hal0 config migrate` walks `/etc/hal0/`
  applying versioned transforms. Schema version stored in `hal0.toml`'s
  `[meta] schema_version = N`. Each migration is a function in
  `hal0/config/migrations/v<N>_to_v<N+1>.py`. Tested with golden inputs

---

## 6. UI work

### v1 views (Vue 3, Tailwind 4)

1. **`Dashboard.vue`** — system health rail, slot summary cards, "your hardware can run these models" tease, link to FirstRun if no models installed
2. **`Slots.vue`** — list, per-slot card with status (state machine!), inline log tail, load/unload/restart/swap actions, "create slot" → modal with hardware-aware form
3. **`Models.vue`** — registry, downloads with progress, slot assignment, deletion
4. **`Hardware.vue`** — GPU/NPU/RAM/disk detect, current allocation across slots, "your NPU is idle" hints, `hal0 probe` re-run
5. **`Logs.vue`** — API + per-slot logs, SSE tail, filters (level, slot, time range)
6. **`Settings.vue`** — config editor (`/etc/hal0/hal0.toml`), update channel, telemetry toggle, dangerous-actions section
7. **`Providers.vue`** — external upstreams (OpenRouter etc.), API key entry, test button
8. **`FirstRun.vue`** — wizard: model picker (Qwen3 4B / Llama 3.2 3B / Phi-3 Mini / custom HF URL), license accept, "start chatting" deep link to OpenWebUI

Plus shell: `Sidebar.vue`, `TopBar.vue`, `CommandPalette.vue`,
`ToastContainer.vue`, `Modal.vue`, `RestartBanner.vue`, `StatusRail.vue`.

### Polish bar

- Dark mode default, no light toggle in v1
- Mobile-responsive read paths; write paths show "use a larger screen"
- SSE-based realtime (no polling indicators); status changes appear within 1s
- Hardware-aware slot form — VRAM fit, RAM fit, "this will swap to disk" warnings
- Every async action emits a toast (success + failure paths)
- Empty states deep-link to creation flows
- Loading skeletons on every initial data fetch

### Strip

Delete entirely (source + folder):
- `views/Chat.vue`, `views/Benchmarks.vue`, `views/Memories.vue`,
  `views/Fixlog.vue`, `views/Presets.vue`, `views/rag/*`, `views/Projects.vue`,
  `views/Training.vue`, `views/training/*`, `views/Agents.vue`,
  `views/AgentSpecs.vue`, `views/Teams.vue`, `views/TeamDetail.vue`,
  `views/HALOnotes.vue`, `views/Rag.vue`, `views/Notebooks.vue`,
  `views/Tasks.vue`, `views/Extensions.vue`, `views/Metrics.vue`
- `components/clawteam/*`, `components/rag/*`

---

## 7. Installer + first-run wizard

### `install.sh` flow

1. Pre-flight: Linux, systemd present, root or sudo, ≥20GB free in `/var/lib`, ports 8080 + 3001 free, docker installed and current user in docker group (or sudo). Each check fails with a fix-it message
2. Download `hal0-vX.Y.Z-linux-x86_64.tar.gz` + `.sig` from `hal0.dev/releases/latest.json` (channel = stable | nightly)
3. Verify signature (cosign keyless against the release OIDC identity)
4. Lay down `/usr/lib/hal0-X.Y.Z/`, atomic-swap `/usr/lib/hal0/current` symlink
5. If first install: write `/etc/hal0/` defaults; if upgrade: skip
6. Hardware probe → `/etc/hal0/hardware.json` + default slot configs derived from detected NPU/GPU
7. Install + enable systemd units (`hal0-api`, `hal0-openwebui`, `hal0-slot@.service` template)
8. Pull toolbox images in background (`docker pull` for `hal0-toolbox-vulkan` etc. + `open-webui` container)
9. Start `hal0-api` + `hal0-openwebui`. **Do not** auto-start slots — that happens after model pick
10. Print URLs and "next: open the dashboard"

`install.sh` is non-interactive. All overrides via env:
`HAL0_CHANNEL`, `HAL0_AUTO_PULL`, `HAL0_INSTALL_DIR`, `HAL0_PORT`,
`HAL0_OPENWEBUI_PORT`.

### First-run wizard (dashboard route)

Triggers when `/var/lib/hal0/models/` is empty. Page asks:

1. **Pick a default model** — curated list with size + VRAM + license:
   - Qwen3 4B (general, vision, 4GB)
   - Llama 3.2 3B (general, 2GB)
   - Phi-3 Mini (general, fast, 2.4GB)
   - Custom Hugging Face URL
2. **License confirm** — surfaces each model's license (Apache 2.0 / Llama / etc.)
3. **Download + assign** — pulls model, assigns to `primary` slot, starts the slot
4. **Done** — "open chat" link to OpenWebUI

---

## 8. OpenWebUI integration

### Bundling shape

OpenWebUI runs as `hal0-openwebui.service`, a systemd unit invoking
`docker run` against `ghcr.io/open-webui/open-webui:main` (pinned per
hal0 release). State dir mounted from `/var/lib/hal0/openwebui/`.

### Prewired

Installer writes `/etc/hal0/openwebui.env`:

```
OPENAI_API_BASE_URLS=http://127.0.0.1:8080/v1
WEBUI_AUTH=False
WEBUI_NAME=hal0
ENABLE_OPENAI_API=True
ENABLE_OLLAMA_API=False
DATA_DIR=/app/backend/data        # mounted to /var/lib/hal0/openwebui
DEFAULT_LOCALE=en
```

Dashboard sidebar has a single "Chat" item with
`href="http://<host>:3001"` and `target="_blank"`. Read host from
`/api/config/urls` so it's correct after install.

---

## 9. Update mechanism

```
hal0 update [--channel=stable|nightly] [--check] [--rollback]
```

- Check: GET `hal0.dev/releases/latest.json?channel=stable` returns
  `{version, url, sig_url, manifest_url, min_data_version}`
- If `version > current`:
  - Download tarball + sig to `/var/lib/hal0/cache/`
  - Verify cosign signature against `hal0-dev/hal0` GitHub OIDC identity
  - Extract to `/usr/lib/hal0-<new>/`
  - Run any pending config migrations (`hal0 config migrate` if `schema_version` advanced)
  - Atomic-swap `/usr/lib/hal0/current` symlink
  - `systemctl restart hal0-api` (slots untouched unless `--restart-slots`)
  - Old version retained at `/usr/lib/hal0-<old>/` for rollback
- Rollback: swap symlink back, restart API
- Dashboard polls `/api/updates/check` on a 24h interval, shows
  `RestartBanner.vue` when an update is available

Channels:
- `stable` — tagged releases, signed, default
- `nightly` — every `main` push (signed by CI OIDC), opt-in via channel switch in Settings or `hal0 update --channel=nightly`

---

## 10. Test strategy

### Unit (pytest)

- Every ported module gets unit tests with mocked systemd / docker / HTTP
- Aim: 70%+ line coverage on `hal0/slots/`, `hal0/dispatcher/`, `hal0/config/`
- Run on every PR

### Integration (β, CI)

- GitHub Actions Linux runner pulls a tiny model (Qwen3 0.5B GGUF) cached
  across runs
- Builds `hal0-toolbox-vulkan` image (CPU-only Vulkan baseline)
- Starts `hal0-api` + `hal0-slot@ci-test` in a netns; runs through:
  - load → verify ready
  - `/v1/chat/completions` round-trip
  - swap model → verify
  - unload → verify
  - state machine transitions visible via SSE
- ~10 min per run; required for PR merge
- ROCm + NPU paths covered by a separate release-gate `make release-test`
  run on the `hal0-test` LXC, not CI

### E2E (γ, Playwright)

Critical paths, each a separate spec:

1. **FirstRun wizard** — empty state → pick model → see slot ready → click "open chat" → OpenWebUI loads → models populated
2. **Slot lifecycle** — create slot via form → load → see state transitions in card → restart → unload → delete
3. **Model management** — download model → assign to slot → see in OpenWebUI picker → delete model → verify slot unassigned
4. **Settings** — change a config value → restart banner appears → restart → value persists
5. **Logs** — open logs page → filter to slot → tail shows new lines on slot activity
6. **Hardware page** — probe re-runs on click → hardware.json updates → slot form fit warnings reflect new state
7. **Update flow** — mock the `/api/updates/check` response → see banner → trigger update → see rollback option

Runs on PR with browser cached, ~8 min total.

---

## 11. Dev environment + migration plan

### Three boxes, three jobs

- **hal0-dev** (10.0.1.141, this VM, RTX 4080): code lives here. IDE, fish shell, local toolchain. Backend logic + UI dev + installer scripting. Vulkan / CUDA dev for non-NPU paths
- **hal0-test** (new Proxmox LXC, 10.0.1.221 or similar, Strix Halo passthrough): **installer QA target**. Wiped between release candidates. Every RC runs through `wipe → install → smoke test`. Also exercises NPU + ROCm paths that CI can't
- **haloai** (10.0.1.220, existing): untouched until v1 cuts over. Continues running haloai + Hermes + your daily slots

### Cutover (post-v1.0)

When hal0 v1 is shipped + tested:

1. Back up the haloai LXC's `/opt/haloai/openwebui/webui.db` and any user-relevant slot configs
2. Run `hal0` migration tool (one-shot script): translates haloai TOMLs to hal0 schema, copies openwebui state, points slot model paths at the existing `/mnt/dock-models` / `/mnt/ai-models` shares
3. Stop all `haloai-*.service` and `hermes-*.service` units; disable
4. Run `install.sh` on the haloai LXC
5. Restore migrated data into `/etc/hal0/` and `/var/lib/hal0/`
6. Start hal0; verify
7. After a week of stability: `rm -rf /opt/haloai /root/.hermes-next`

The haloai LXC becomes the prod hal0 box. `hal0-test` remains the QA LXC.

---

## 12. Toolbox images

Rename + republish. Current source: `ghcr.io/hal0ai/amd-strix-halo-toolboxes:*-server`
(kyuz0-derived, pending PRs #86/#87 upstream).

v1 images:
- `ghcr.io/hal0-dev/hal0-toolbox-vulkan:v1`
- `ghcr.io/hal0-dev/hal0-toolbox-rocm:v1`
- `ghcr.io/hal0-dev/hal0-toolbox-flm:v1` (NPU)
- `ghcr.io/hal0-dev/hal0-toolbox-moonshine:v1`
- `ghcr.io/hal0-dev/hal0-toolbox-kokoro:v1`

Each tagged + signed (cosign). hal0 release manifest references specific
image digests, so an update pulls the exact images known-good for that
hal0 version. Old images retained for rollback.

When kyuz0 PRs land, mirror back to upstream and re-converge.

---

## 13. CLI surface

```
hal0 status                          # system + slot summary (JSON | table)
hal0 probe                           # re-run hardware detection
hal0 slot list
hal0 slot load <name> [--model M]
hal0 slot unload <name>
hal0 slot restart <name>
hal0 slot swap <name> --model M
hal0 slot logs <name> [--follow]
hal0 model list
hal0 model pull <ref>                # HF ref or curated alias
hal0 model rm <ref>
hal0 model assign <ref> --slot S
hal0 update [--channel] [--check] [--rollback]
hal0 config show
hal0 config edit                     # $EDITOR
hal0 config migrate
hal0 config validate
hal0 uninstall [--keep-data]
```

Implementation: Typer (typed click). Each command hits the local API on
`127.0.0.1:8080` so the CLI is a thin client. Daemon mode is `hal0
serve` (used by the systemd unit).

---

## 14. Telemetry

**Off by default**, opt-in via Settings page or `HAL0_TELEMETRY=1` env.
Anonymous: hardware class (GPU vendor, VRAM bucket), hal0 version, OS,
slot count, daily ping. No model names, no IPs, no error contents, no
config contents.

Endpoint: `https://telemetry.hal0.dev/v1/ping` (deferred until hal0.dev
exists). Code path lives in `hal0/telemetry/` from day one; the toggle
defaults to off, but the plumbing is real so v0.2 enabling it isn't a
refactor.

---

## 15. Phased milestones

Working assumption: 1 person full-time + Claude as pair. Adjust if not.

**Phase 0 — scaffold (week 1)**
- New `hal0-dev:/home/halo/dev/hal0/` repo, `git init`
- pyproject.toml, package layout, FastAPI app factory, empty routers
- Vue 3 + Tailwind 4 scaffold; sidebar, dark theme, empty 9 view stubs
- CI skeleton (GitHub Actions, ruff + pytest)
- README, ARCHITECTURE.md, CONTRIBUTING.md drafted

**Phase 1 — port core (weeks 2-3)**
- Port slot manager → `hal0/slots/manager.py`
- Port dispatcher → `hal0/dispatcher/router.py`
- Port providers (llama_server, flm, moonshine, kokoro)
- Port registry, hardware probe, upstreams, config (with pydantic schema)
- `hal0-slot@.service` template unit, env writer (atomic)
- Unit tests for each module
- API routers wired up; `/v1/*` and `/api/slots/*` working end-to-end

**Phase 2 — installer + LXC QA (week 4)**
- Provision `hal0-test` LXC with Strix Halo passthrough
- Write `install.sh` (signed-release path) + uninstall
- Hardware probe → default slot configs
- Toolbox image build + publish (`hal0-toolbox-vulkan` first)
- Run install on hal0-test, fix everything

**Phase 3 — reliability Tier 1 + 2 (week 5)**
- Atomic env writes, schema validation, structured errors
- Tightened health probes, adaptive cold-boot
- Dispatcher decision logging, prefetch tuning
- All audit-identified bugs closed

**Phase 4 — UI polish (weeks 6-7)**
- All 9 views built out, dark mode, hardware-aware slot form
- SSE plumbing for slot status + log tail
- FirstRun wizard end-to-end with model download
- Empty states, loading skeletons, toasts everywhere

**Phase 5 — Tier 3 reliability + OpenWebUI prewire (week 8)**
- Slot lifecycle state machine
- Request coalescing / single-flight
- Config migration tooling
- OpenWebUI systemd unit + env prewire
- `hal0 update` mechanism + signed releases pipeline

**Phase 6 — γ testing + release prep (week 9)**
- Playwright suites for the 7 critical paths
- Release notes draft
- `make release-test` on hal0-test (full NPU + ROCm + Vulkan matrix)
- Bug bash

**Phase 7 — v1.0 cut (week 10)**
- Tag v1.0.0
- Cut signed release artifacts
- Migrate haloai LXC → hal0 (cutover)
- Public launch (timing depends on repo-home + license decision — separate call)

**Total: ~10 weeks of focused work.**

---

## 16. Deferred decisions (track explicitly)

These were intentionally not settled during the grilling and need their
own decisions before relevant milestones:

- **Repo home + license** (deferred from Q4). Decide before phase 6 release prep
- **Hermes shutdown timing** on the haloai LXC. Decide at cutover (phase 7)
- **`hal0.dev` web property** scope. Marketing site? Just `install.sh` + release JSON? Decide before phase 6
- **Public launch story** — blog post? HN? home AI subreddit? Decide before phase 7
- **Contribution model** — accepting external PRs from day one? GH issues open? Decide before phase 7

---

## 17. Risks + mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Slot lifecycle state machine refactor balloons in scope | Medium | Time-box phase 5 at 5 days; if not converging, fall back to status-snapshot model and defer state machine to v0.2 |
| Cosign release pipeline + signed-artifact verification has nasty edges | Medium | Prototype in phase 2 against a throwaway release, not phase 5 |
| Toolbox images on `ghcr.io/hal0-dev/` blocked by org provisioning | Low | Use `ghcr.io/<personal>/` initially; transfer post-v1 |
| OpenWebUI internal API changes break prewire env | Low | Pin OpenWebUI container version per hal0 release; test on every update bump |
| Strix Halo NPU driver flakiness on `hal0-test` LXC delays integration | Medium | Build CI path on Vulkan-CPU first; NPU is release-gate only, not per-commit |
| Self-update mechanism corrupts an install | Low–Medium | Atomic symlink swap + retained previous version + `hal0 update --rollback` command. Test rollback as part of release-gate |
| Scope creep ("just add memory while we're in there") | High | This document is the scope. Anything else is v0.2. Push back hard |

---

## 18. Definition of done — v1.0

- [ ] Fresh LXC: `curl -fsSL hal0.dev/install | bash` → install completes in <5 min
- [ ] Dashboard at `:8080`, OpenWebUI at `:3001`, both reachable
- [ ] FirstRun wizard downloads a model, assigns to slot, slot reports ready
- [ ] Chat works end-to-end (OpenWebUI → hal0 → llama.cpp slot → response)
- [ ] All 9 views render, dark mode, hardware-aware slot form works
- [ ] SSE log tail works without manual refresh
- [ ] `hal0 update --channel=nightly` upgrades, `--rollback` reverts
- [ ] `systemctl restart hal0-api` doesn't kick running slots
- [ ] All Tier 1, 2, 3 reliability items closed
- [ ] CI green (unit + slot integration), Playwright green on 7 paths
- [ ] Release-gate `make release-test` passes on hal0-test (NPU + ROCm + Vulkan)
- [ ] README, install docs, slot docs, model docs written
- [ ] haloai LXC migration script tested on a hal0-test clone of haloai's data

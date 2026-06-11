# Lemonade Removal — Full Container Switchover Design

- **Date:** 2026-06-10
- **Status:** Approved (interactive brainstorming session)
- **Builds on:** container-runtime epic #652 (closed — chat/agent GPU slots on podman), `hal0-container-runtime-design-2026-06-08.md`
- **Supersedes:** #402 (lemond typed-adapter end-state PRD — obsoleted by removal)

## 1. Goal & end state

Lemonade (the `lemond` daemon, `hal0.lemonade` package, `LemonadeProvider`, FLM trio router, lemonade API routes, installer steps, UI hooks/banners/settings) is **completely removed** from the platform and codebase. Every slot — chat, agent, npu, stt, embed, tts, rerank, utility, img — runs as a podman container under `hal0-slot@<name>.service`, managed by `ContainerProvider`, fully integrated into the dashboard.

**Non-goals (this epic):** VibeVoice GPU TTS profile (kokoro first; vibevoice later), OGA/non-FLM NPU runtimes, multi-model NPU concurrency (hardware can't), Open WebUI changes.

## 2. Decisions (user-approved 2026-06-10)

| # | Decision |
|---|----------|
| D1 | NPU = **one customizable container slot** (trio-capable), stt/embed become routing aliases. One FLM process per NPU; model swap = container restart. |
| D2 | TTS target = **Kokoro CPU container**. VibeVoice deferred. |
| D3 | **Rerank and utility both containerized** (llama-server toolbox images). |
| D4 | ComfyUI = **full slot integration + exclusive GPU arbitration** (docker → podman). |
| D5 | **Profile CRUD in the dashboard** (create/edit/delete via API; seeds protected). |
| D6 | Backend (vulkan/rocm) is a **profile property**; profile becomes **editable in the slot edit drawer** for GPU slots. |
| D7 | **Default profile per device class** (gpu→`vulkan-std`, npu→`flm-npu`, cpu-tts→`kokoro-cpu`) for create-modal preselect and legacy-slot migration. |
| D8 | Phased rollout A–F; lemonade stays as rollback until Phase E. |

## 3. Slot-by-slot plan

| Slot | Image (profile) | Devices | Notes |
|---|---|---|---|
| `chat`, `agent` | rocmfp4 toolbox (existing) | kfd + dri | Done (epic #652). Unchanged. |
| `npu` | `ghcr.io/hal0ai/hal0-toolbox-flm:v1` (`flm-npu`) | `/dev/accel/accel0`, `/dev/dri/renderD128` | `flm serve <tag>`; `asr`/`embed` booleans + `context_size` + `extra_args` in TOML, surfaced in edit drawer. `--ulimit memlock=-1`, XRT `LD_LIBRARY_PATH` per `FLMProvider.container_spec()`. Model cache mount: `/var/lib/hal0/.config/flm/models`. |
| `stt`, `embed` | *(no container when backend=npu)* | — | Routing aliases → npu container's static port. Capabilities-apply still flips them to CPU/GPU container backends when NPU trio is off. |
| `tts` | Kokoro CPU image (`kokoro-cpu`) | none | New profile + image pin in manifest.json. Fixes current error state (kokoro/vibevoice config-state mismatch). |
| `rerank` | llama-server toolbox (`vulkan-std` default, rocm swappable) | dri (+kfd for rocm) | `--reranking` lives in slot `[server].extra_args` (slot-intrinsic, not a profile concern). |
| `utility` | llama-server toolbox (`vulkan-std` default) | dri | Straight clone of chat recipe. |
| `img` | `kyuz0/amd-strix-halo-comfyui` digest-pinned (`comfyui`) | kfd + dri | docker → podman, `img.toml` + `ComfyUIProvider` + dashboard card. Diagnose/fix the observed 100%-CPU idle spin during migration. |

## 4. NPU design detail

- The XDNA NPU is single-tenant: one FLM process, one model. The container **is** the model instance — swap = restart `hal0-slot@npu` with a new `flm serve <tag>` argv. "One container per model" holds sequentially; concurrent NPU containers are impossible (hw alloc conflicts).
- `npu.toml` gains `[npu] asr = bool, embed = bool` (orchestrator-owned; replaces lemond `flm.args` read-modify-write — config file becomes the single source of truth, eliminating the lemond-config drift class).
- FLM model catalog: existing host-flm probe (`flm list`, 2026-06-07 plan) feeds the model dropdown; FLM tags remain their own namespace.
- #578 (FLM `/v1/embeddings` 404) re-tested against the bare container. If it reproduces → upstream FLM issue; embed toggle ships dark with a UI note until fixed.
- #679 (drop `agent` from `NPU_SEEDED_SLOTS`) lands as part of Phase A.

## 5. Dispatcher changes

- **Delete `FLMTrioRouter`** (`dispatcher/flm_trio.py`). It existed to discover lemond's dynamic FLM child `backend_url`; container ports are static. STT/embed-on-NPU becomes plain port routing in the dispatcher chain.
- Delete `lemonade_proxy.py` catch-all; `/v1/*` fully dispatcher-owned.
- `npu_swap_status.py` reads container/systemd state instead of lemond `/v1/health`.
- `recover_evicted_slot` removed — nuclear-evict is a lemond failure mode; systemd `Restart=` policy replaces it.
- Fix #485 (gateway can't dispatch rerank + STT) as part of the alias/port routing work — root cause is the same modality-dispatch gap.
- Legacy `proxy.resolve_slot` FLM-tag heuristic (`":" → npu`) survives but routes to the container port (interacts with open PR #649 which retires Tier-4 — coordinate, don't duplicate).

## 6. Observability & lifecycle replacements

| Lemond-coupled subsystem | Replacement |
|---|---|
| `MetricsShim` + `prometheus_format` (poll lemond `/v1/stats`) | Slim per-slot collector polling each container's llama-server `/metrics` + health; same Prometheus exposition route. FLM metrics: from the npu container's endpoints. |
| Journal lemond log bridge (`LemondLogRing`, WS) | All slots log to journald via their units; journal reads `hal0-slot@*` streams uniformly (container slots already do this). |
| `IdleDriver` (global idle unload) | Optional per-slot `idle_stop_minutes` (systemd stop), default **off**. |
| Slot-list `_lemonade_state_enrichment` (`/v1/health` per list) | podman-inspect path (#663/#681) becomes the only path. |
| Capabilities orchestrator `flm.args` writes via lemond client | Writes `npu.toml` booleans (see §4). |
| `server_models_gen` (631 lines) + auto-regen hook (#594) | Deleted. registry.toml is the catalog source of truth; FLM tags via host-flm probe. |
| `api/_settings_apply.py` `SERVICE_LEMONADE` taxonomy | Replaced by per-slot container apply entries (restart slot unit). |

## 7. ComfyUI integration + exclusive GPU arbitration

- Migrate the standalone docker container to podman as `hal0-slot@img` with `img.toml`, `ComfyUIProvider` (already in `_PROVIDERS`, #682), digest-pinned image, port bound per slot config.
- **GPU arbiter** (SlotManager): GPU container slots declare an exclusive group — `llm` (chat/agent/utility/rerank) vs `img`. On an image-gen request with `img` not resident: stop LLM slot containers (config preserved in TOML), start `img`, run job. After a configurable idle window with no img jobs (default 5 min), restore the previous LLM set. Manual mode-pin toggle in dashboard + API. LLM requests during image mode → clear 503 with `Retry-After`, surfaced as a "GPU: image mode" banner.
- **In-flight coordination:** another session is concurrently building the ComfyUI Image-Gen tab + read-only `/api/comfyui` telemetry proxy + feature-gated switchover on the slots page. Phase D **builds on that work** (consumes its endpoints/tab) rather than duplicating; reconcile claims via the wip board before starting D.
- #599 (persist image-gen settings) folds into `img.toml` slot schema fields.

## 8. Profiles

- **Seeds (existing):** `moe-rocmfp4`, `dense-mtp-rocmfp4`, `vulkan-std`. **New seeds:** `flm-npu`, `kokoro-cpu`, `comfyui`. Seeds live in `SEED_PROFILES` (schema.py) mirrored in `installer/etc-hal0/profiles.toml`.
- **CRUD:** `POST/PUT/DELETE /api/profiles` writing `profiles.toml`; seed profiles immutable (edit = clone). Profiles page upgraded viewer → editor (image, flags, mtp fields, validation via `ProfileConfig`).
- **Drawer:** profile becomes an editable dropdown in the edit drawer for GPU slots (change → container restart on new image). `npu`/`tts`/`img` show fixed profiles (silicon/runtime constraints). Remove the hardcoded `device: "gpu-rocm"` in the create modal — derive from profile.
- **Flag precedence (existing, unchanged):** model/port/ctx (slot) → profile flags → slot `[server].extra_args` (slot wins).
- **Per-device defaults (D7):** used by create-modal preselect and Phase E auto-migration of profile-less legacy slots.

## 9. Schema & config migration

- `runtime` literal shrinks to `"container"`; field kept one release as deprecated. Any `runtime="lemonade"` (or absent-with-no-profile) slot auto-migrates on load: assign device-class default profile, journal a warning.
- `"lemonade"` removed from `_PROVIDERS` and `_VALID_PROVIDERS`; provider field re-validated.
- One-shot deploy migration rewrites `/etc/hal0/slots/*.toml` + `state.json`: fixes tts (kokoro-v1 vs vibevoice state) and rerank (jina vs bge state) config/state mismatches observed live.
- `hal0 capabilities migrate-to-lemonade` CLI command deleted.

## 10. Installer / uninstaller

- Remove: lemonade bundle download (SHA-pinned tarball → `/opt/lemonade`), `ppa:lemonade-team/stable`, `hal0-lemonade.service` + drop-ins, lemond `config.json` seeding, `server_models_gen` invocation.
- Keep: FLM host `.deb` (probe/pull path), `libxrt-npu2` and NPU prerequisites (host probe + device sanity).
- Uninstaller learns to clean **legacy** lemond installs (`/opt/lemonade`, `/var/lib/hal0/lemonade`, unit + drop-ins, PPA) — required for upgrades of existing boxes, not just fresh installs.
- New seed TOMLs: `img.toml`; updated `npu/stt/embed/tts/rerank/utility` seeds with profiles.

## 11. UI

- **Remove:** `useLemonade*` hooks, `ENDPOINTS.lemonade*`, 8+ lemond banners (offline/evict/drift), settings Runtime/lemond section, `lemonade_state` branching in slots/slot-status, "Restart lemond" palette action, FLM-install modal copy referencing `hal0-lemonade`, runtime dropdown in slot modals, lemond journal source.
- **Add:** NPU drawer asr/embed toggles + FLM model dropdown; profile dropdown in edit drawer (D6); profiles page CRUD (D5); img slot card with generation/arbitration status (building on the in-flight Image-Gen tab); "GPU: image mode" banner + manual mode toggle; container-native footer chips (replace `useLemondRollup`).
- Mock fixtures (`HAL0_DATA`, γ-suite) regenerated for container-only state.

## 12. Phasing — each phase lands green on main, deploys to CT105, soaks before the next

| Phase | Scope | Key risks addressed first |
|---|---|---|
| **A. NPU cutover** | `flm-npu` profile + npu container slot + stt/embed alias routing + asr/embed toggles + #679 + #578 retest | Highest-risk slot while lemonade still exists as rollback |
| **B. Voice** | kokoro-cpu profile + tts container + #485 dispatch gap fix | |
| **C. Rerank + utility + profile UX** | vulkan containers ×2, profile-editable drawer (D6), profile CRUD (D5), device-class defaults (D7) | |
| **D. ComfyUI** | podman migration + img slot + GPU arbiter + dashboard integration (builds on in-flight Image-Gen tab session) | Coordinate via wip board |
| **E. Lemonade extraction** | Delete `hal0.lemonade` pkg, `LemonadeProvider`, 3 API route files, FLM trio router, UI removal (§11), observability replacements (§6), schema migration (§9), installer (§10); stop+remove lemond on CT105 | Destructive step lands last, after A–D soak ≥ a few days |
| **F. Docs/promo** | ARCHITECTURE/PLAN/README/CONTEXT, `docs/operate/lemonade.md` → container-runtime ops guide, hal0-web CONTENT_BRIEF sync | |

Rollback: A–D are additive (lemond keeps running, owns fewer slots each phase). E is the only destructive phase; its deploy step snapshots `/etc/hal0` + lemond config before removal.

## 13. Testing

- TDD throughout. ~70 test files touched; `tests/lemonade/` (~2.9k lines) + trio/lemonade-bridge suites deleted in E, replaced by: container metrics collector, GPU arbiter, alias routing, profile CRUD, schema migration suites.
- Per-phase e2e validation on CT105 (live inference round-trips per modality; γ-suite for UI).
- Agent strategy: Sonnet for mechanical fan-out (test rewrites, UI hook removal, doc sweep); Opus for SlotManager/dispatcher/arbiter surgery and review gates.

## 14. Risks & open questions

| Risk | Mitigation |
|---|---|
| FLM trio asr/embed broken in container (#578, gemma4-e4b alloc fail) | Retest first thing in Phase A; ship toggles dark + upstream issue if real |
| GPU arbiter races (img job vs in-flight LLM gen) | Arbiter drains in-flight requests (dispatcher single-flight) before stopping slots; manual pin as escape hatch |
| Shared CT105 dev tree mid-deploy collisions | `wip hal0 status` + claims before every deploy; phases deployed via `scripts/deploy.sh` |
| ComfyUI 100%-CPU idle spin (observed live, 3 days) | Diagnose during D migration; digest-pin a known-good image |
| Prometheus consumers of lemond-shaped metrics | Keep metric names stable where semantics survive; document renames in F |

# Handoff — 2026-05-15 autonomous session

## Headline

The full-stack scope from the previous handoff is now in. Memory bar bug
fixed; `/api/upstreams` implemented; slot template settled on
`User=root`; slot lifecycle + model CRUD wired through; CLI ships real
HTTP calls; installer rewritten to actually install hal0 into a venv;
slot grid uses the new haloai-style `SlotCard`; concurrent-slot
inference verified on the hal0-test LXC.

353 pytest pass, 2 skipped (template integration — same skips as the
previous handoff). UI builds clean (348ms vite build).

## What landed (commits, pushed to `origin/main`)

- **`34da4ea`** fix(hardware): unified-memory pool no longer
  double-counts RAM + GTT on UMA
- **`96c6dc7`** feat(hardware,api): merge live GTT/RAM/VRAM counters
  into `/api/stats/hardware`
- **`f0de418`** feat(api,cli): wire slot/model write paths and CLI HTTP
  client
- **`4d0a847`** feat(ui,installer): SlotCard grid for /slots;
  install.sh rewrite

## Memory bar — what was wrong, what it does now

Probe-side: on Strix Halo UMA, `vram_mb=GTT pool` and `ram_mb` came from
`/proc/meminfo` which reports the LXC's cgroup quota (66 GiB) not the
host's 128 GiB. The dashboard then computed total = `ram + gtt` →
169 GiB on a 128 GiB machine.

Fix:
- `HardwareInfo.unified_memory_mb` is a new derived field. Computed from
  `dmidecode -t memory` (sum of physical DIMM sizes) when `/proc/meminfo`
  shows a cgroup-restricted view; otherwise mirrors `ram_mb`.
- `/api/hardware` now flattens `is_uma`, `unified_memory_mb`, splits
  `gtt_total_mb` vs `vram_total_mb` (was aliased on UMA so both pointed
  at the GTT pool).
- `/api/stats/hardware` merges this process's `HardwareStats` snapshot
  (`gtt_used_mb`, `vram_used_mb`, `ram_used_gb`, `gpu_util`) into the
  payload — previously the route only proxied upstreams, which on the
  single-LXC deployment all returned `null`.
- `Dashboard.vue` reads `unified_memory_mb` directly, no longer sums RAM
  + GTT, subtracts GTT from system-RAM in the breakdown so they don't
  both bill the same bytes.

Live payload from the LXC now reports:
```
unified_memory_mb=131072 ram_total_mb=66000 ram_used_mb=256
gtt_total_mb=107520 gtt_used_mb=8215.8
vram_total_mb=0      vram_used_mb=878.3
is_uma=true
```

## Slot/model write paths (was 501 stubs)

Wired to `SlotManager` and `ModelRegistry`:

- `POST /api/slots` — create with `SlotConfig` body
- `DELETE /api/slots/{name}` — stop + remove TOML, override, env, state
- `GET /api/slots/{name}/config` — raw TOML as dict (new public
  `SlotManager.get_config()`)
- `PUT /api/slots/{name}/config` — shallow merge updates
- `PATCH /api/slots/{name}/defaults` — sugar for editing `[model]`
- `POST /api/slots/{name}/backend` — backend swap
- `GET /api/slots/{name}/logs` — `journalctl -u hal0-slot@{name} -n N`
- `GET /api/slots/{name}/logs/stream` — SSE journalctl `-f`
- `POST /api/models`, `PUT /api/models/{id}`, `DELETE /api/models/{id}`
- `GET /api/upstreams`, `GET /api/upstreams/{name}`, `POST .../test`
- `GET /api/providers`, `GET /api/providers/catalog`

`/api/models/{id}/pull` is still 501 — see "remaining gaps" below.

## CLI

Every subcommand under `hal0 {slot,model,config}` and the top-level
`hal0 {status,probe}` now talks to the daemon via the new `api_*`
helpers in `cli/_shared.py`. Verified end-to-end:

```
$ HAL0_API_URL=http://10.0.1.230:8080 hal0 status
hal0 v0.0.0  · slots=1 · upstreams=1
 Slots
 ┃ Name    ┃ State ┃ Model                        ┃ Port ┃
 │ primary │ ready │ qwen2.5-0.5b-instruct-q4_k_m │ 8081 │
```

`hal0 config show/edit/validate/reload/hardware` work locally
(`HAL0_HOME` aware). `hal0 slot logs <name> --follow` tails SSE.

## Installer

`installer/install.sh` rewritten — the previous version laid out
filesystem scaffolding but never actually installed the Python code or
wired a runnable `hal0` binary. New version:

1. Creates `/opt/hal0/.venv` (or `$PWD/.hal0-dev/.venv` in `--dev`)
2. `pip install -e <repo>` so the venv's `hal0` cli is the real one
3. Writes `/etc/hal0/hal0.toml`, `api.env`, `upstreams.toml` defaults
   (never clobbers existing files)
4. Drops in `hal0-api.service` (pointing at the venv binary) and the
   canonical `packaging/systemd/hal0-slot@.service`
5. Runs the hardware probe so `/etc/hal0/hardware.json` exists before
   the daemon starts
6. `systemctl enable --now hal0-api` (unless `--no-start` / `--dev`)

Dry-run verified: `bash installer/install.sh --dev` produces a working
hal0 venv with the cli reachable at `.hal0-dev/.venv/bin/hal0`.

## Slot template — `User=root`

`packaging/systemd/hal0-slot@.service` is now canonically `User=root`
with a rationale comment: the workload runs inside a Docker/Podman
container which is the real sandbox boundary; a dedicated `hal0` UID +
docker-group bootstrapping is too brittle across distros for v1. A
post-install Stage-2 drop-in can flip back to `User=hal0` once an
operator has prepared the host. The LXC running on 10.0.1.230 has been
re-synced with this template.

## UI polish — SlotCard

`ui/src/components/SlotCard.vue` is a new compact slot card based on the
haloai layout (status dot + name + port, model line, four-stat row
(T/s · ACT · MEM · UP), dual-series TPS sparkline, footer with model
picker + edit/logs/restart/stop/start buttons). All colours come from
the `--color-*` CSS variables, no Tailwind utility soup. `Slots.vue`
now renders the cards in an auto-fill grid; modals/drawers/keyboard
shortcuts are unchanged.

Models view + Hardware view + Settings + Providers were left as the
existing layouts (table or stacked-cards) — they read the same data
shapes the new API surface returns.

## NPU + embed + voice simultaneous slot test (user request)

Created `embed` (llama-server vulkan) and tried to create `stt`
(moonshine), `tts` (kokoro), `npu` (flm). Result:

- ✅ `primary` + `embed` ran concurrently on the same iGPU. GTT went
  from 8.2 GB → 9 GB. Direct inference against both returned in <200 ms
  with ~258 tok/s.
- ✅ Gateway dispatch worked: `POST /v1/chat/completions` hit the
  right slot and answered.
- ❌ `stt`, `tts`, `npu` failed to come healthy with
  `slot.health_failed` — the FLM / Moonshine / Kokoro toolbox images
  (`ghcr.io/hal0-dev/hal0-toolbox-{flm,moonshine,kokoro}:v1`) are not
  yet built or published. The error envelope is correct; the failure
  is in the image supply chain, not the dispatch path.
- Test slots were cleaned up; LXC is back to the single-`primary`
  state.

The path that needs work: build & publish the FLM/Moonshine/Kokoro
toolbox images (PLAN §17 / GHCR org provisioning). Once those exist,
re-run the same `create → load` sequence and the four-slot concurrent
voice + NPU embed + chat scenario will go end-to-end.

## Remaining gaps

1. **Model pull** — `POST /api/models/{id}/pull` still 501. The
   download flow needs the curated-models manifest + a streaming HF
   fetcher. The CLI's `hal0 model pull` already routes to it but
   prints the same 501 envelope back. Stage with the FirstRun wizard.

2. **Toolbox images** — only `hal0-toolbox-vulkan:dev` exists. FLM /
   moonshine / kokoro / rocm builds + GHCR push are the unblockers for
   NPU + voice + discrete-GPU loads.

3. **Hardware view live counters** — `Hardware.vue` reads `gtt_used_mb`
   etc. already (it now gets them). Sanity-check the breakdown bar's
   colour-by-pct logic against the new payload shape.

4. **`SlotManager.delete` skips built-in slots** — by design (`embed`,
   `stt`, `tts` are always present). Make sure the UI doesn't show a
   delete affordance on them; the LXC's built-in `embed` was left
   running after the test and required a manual filesystem wipe to
   evict.

5. **`backend: null` on the primary slot's snapshot** — the live `/api/
   slots` response shows `backend: null` even though `/etc/hal0/slots/
   primary.toml` has `backend = "vulkan"`. The transition path writes
   `extra.backend` but the top-level field doesn't get re-hydrated on
   startup. Cosmetic — chips on SlotCard still pick it up via
   `slot.backend` (falls back to extra).

6. **Memory probe drift** — the dmidecode-based fallback could pick up
   stale BIOS info on systems with hot-pluggable DIMMs. Not a hal0
   problem today, but worth a note in the probe docstring.

## Environment quick-ref

- **Dev VM** (this box): `hal0-dev`, 10.0.1.141. Repo at
  `/home/halo/dev/hal0`. Tests:
  `HAL0_HOME=/tmp/hal0-pytest .venv/bin/pytest tests/ -q` → 353 pass.
- **LXC**: `hal0-test`, VMID 230, 10.0.1.230. SSH:
  `ssh -i ~/.ssh/thinmint root@10.0.1.230`. Daemon at `/opt/hal0`,
  logs at `/var/log/hal0/serve.log`. Single `primary` slot ready.
- **Vite dev server**: still bound to 5173, proxies to 10.0.1.230:8080.
- **Restart hal0 on LXC**:
  `ssh -i ~/.ssh/thinmint root@10.0.1.230 'PID=$(ss -lntp | awk -F"pid=" "/:8080/ {split(\$2,a,\",\"); print a[1]}"); [ -n "$PID" ] && kill "$PID"; sleep 2; cd /opt/hal0 && HAL0_TOOLBOX_IMAGE_VULKAN=hal0-toolbox-vulkan:dev nohup .venv/bin/hal0 serve --host 0.0.0.0 --port 8080 > /var/log/hal0/serve.log 2>&1 & disown'`
- **Rsync code to LXC**:
  `rsync -a --exclude .venv --exclude __pycache__ -e 'ssh -i /home/halo/.ssh/thinmint' src/ root@10.0.1.230:/opt/hal0/src/`

## Suggested next session

1. Build the FLM/Moonshine/Kokoro toolbox images (or pull from haloai
   if they already exist there). Push to a temporary registry.
2. Re-run the four-slot concurrent test now that the images are
   reachable.
3. Wire `POST /api/models/{id}/pull` to a real HF streaming download
   with progress events on `app.state` for the dashboard.
4. Pass the `backend: null` cosmetic noise on the primary snapshot.

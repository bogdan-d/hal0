# hal0 architecture

This document covers hal0's internal architecture. For the user-facing
shape (install, ports, filesystem layout), see [`docs/install.md`](./docs/install.md).
For scope and roadmap, see [`PLAN.md`](./PLAN.md).

## Process model

hal0 is a single FastAPI process (`hal0-api.service`) that orchestrates
N systemd-managed inference containers (`hal0-slot@<name>.service`).
OpenWebUI runs as its own systemd unit (`hal0-openwebui.service`).

```
                   ┌─────────────────────────┐
   user/clients ─▶ │  hal0-api  (:8080)      │ ◀─ OpenWebUI (:3001)
                   │  FastAPI + dispatcher   │
                   └────────────┬────────────┘
                                │ systemctl + HTTP probes
                ┌───────────────┼───────────────┐
                ▼               ▼               ▼
        hal0-slot@primary  hal0-slot@embed   hal0-slot@stt   ...
        (llama.cpp)        (llama.cpp)       (Moonshine)
```

Each slot is independent: its own port (8081+), its own model, its own
lifecycle. The API process only owns slot **lifecycle** (load / unload /
restart) and **routing** (dispatcher → slot → response). It never holds
a model in its own memory.

## Module layout

```
src/hal0/
├── api/             # FastAPI app + routers + middleware
│   ├── routes/      # one APIRouter per concern (18 modules incl.
│   │                #   capabilities, backends, images, events, auth)
│   └── middleware/  # error envelope, request id, cors
├── slots/           # slot lifecycle (state machine, unit rendering)
├── dispatcher/      # routing, single-flight, decision logging
├── providers/       # backend abstraction (llama_server, flm, moonshine,
│                    #   kokoro, comfyui)
├── capabilities/    # UX overlay grouping flat slots into capability
│                    #   cards (catalog + config + orchestrator);
│                    #   persists selections in capabilities.toml and
│                    #   reconciles slot TOMLs on every apply
├── registry/        # model registry (atomic TOML, mtime cache, GGUF
│                    #   magic-byte detect, HF-cache repo-name fallback)
├── hardware/        # probe + stats (GPU, NPU, RAM, disk)
├── upstreams/       # external LLM providers (OpenRouter, etc.)
├── config/          # pydantic schemas, TOML loader, migrations
├── auth/            # password + Bearer token storage (per ADR-0001)
├── events/          # in-process pub/sub for SSE streams
├── updater/         # self-update (cosign-verified, atomic swap)
├── installer/       # first-run wizard backend, hardware probe writer
├── voice/           # Moonshine + Kokoro provider glue
├── openwebui/       # companion service env file writer
└── cli/             # `hal0` Typer CLI (incl. `capabilities migrate`)
```

The capabilities layer is a **thin overlay** on the flat slot layer,
not a replacement. Slot configs under `/etc/hal0/slots/*.toml` remain
authoritative; `capabilities.toml` records which capability picks
should be projected back onto those slot files. `hal0 capabilities
migrate` cleans up persisted selections whose (backend, model) pair
is no longer valid — primarily for FLM model-tag namespace drift.

## Key boundaries

- **Slot lifecycle is pure systemd.** The slot manager talks to
  systemctl + filesystem (env files, unit overrides) + journald. It
  doesn't import HTTP client code, doesn't know about models other than
  via the registry, and doesn't make assumptions about backends beyond
  the provider ABC.
- **Dispatcher is HTTP-only.** It does not start/stop slots. It reads
  slot status from the slot manager and routes requests. If a slot is
  offline, it returns a structured error; restarting is a separate API
  call.
- **Providers are stateless.** Each provider (`LlamaServerProvider`,
  `FLMProvider`, `MoonshineProvider`, `KokoroProvider`,
  `ComfyUIProvider`) is a class with `build_env()`, `start_cmd()`,
  `health()`, `infer()`. They don't hold connection state, don't manage
  systemd, and don't share globals. One provider per backend type.
  `FLMProvider` additionally probes `flm list -j` inside the toolbox
  image to advertise its own model-tag namespace
  (`share/flm/model_list.json`) — it does **not** run arbitrary GGUFs
  from the registry.
- **The registry is the only source of truth for "what models exist."**
  Atomic TOML files under `/var/lib/hal0/registry/`. mtime-cached. Slot
  configs reference model IDs from the registry; if a model is deleted,
  any slot referencing it fails to load with a structured error.

## State

Three categories of state, three filesystem locations:

| Kind      | Location              | Examples                                |
|-----------|-----------------------|------------------------------------------|
| Code      | `/usr/lib/hal0/current/` | Python package, UI dist, unit templates |
| Config    | `/etc/hal0/`          | `hal0.toml`, `slots/*.toml`, `providers.toml`, `hardware.json` |
| Runtime   | `/var/lib/hal0/`      | `models/`, `registry/`, `openwebui/`, `slots/<name>/state.json` |

Code is replaceable (every update writes a new versioned dir + flips a
symlink). Config is preserved across updates. Runtime is preserved
across updates and survives uninstall when `--keep-data` is passed.

### Slot lifecycle state machine

The authoritative enum lives in
[`hal0.slots.state.SlotState`](./src/hal0/slots/state.py); transitions are
enforced by `SlotManager._transition()` and persisted atomically to
`/var/lib/hal0/slots/<name>/state.json`.

```
offline → pulling → starting → warming → ready ←──┐
                                  │      ↑        │
                                  │      ↓        │
                                  └──→  idle ←─ serving
                                         │
                                         ↓
                                     unloading → offline
                                         ↑
                                       error
```

| State        | Meaning                                                              |
|--------------|----------------------------------------------------------------------|
| `offline`    | No systemd unit active.                                              |
| `pulling`    | Model files downloading / verifying; unit not yet started.           |
| `starting`   | `systemctl start` issued; container not yet reachable.               |
| `warming`    | Container reachable; model loading or `/v1/models` populating.       |
| `ready`      | Probe converged AND at least one model advertised — safe to route.   |
| `serving`    | At least one inference request in flight on this slot.               |
| `idle`       | Container up but cannot fulfil requests right now. Two sub-cases:    |
|              | (a) `--model ""` / empty `/v1/models` — process-up-no-model;         |
|              | (b) ready slot quiet for longer than the idle timeout.               |
| `unloading`  | Graceful `systemctl stop` in progress.                               |
| `error`      | Failed; details in `state.json.message` and journald.                |

`SlotManager.status()` runs a bidirectional reconciler against
`systemctl is-active`:

- A `ready`/`serving`/`idle` state with a dead unit → transition to
  `error`.
- An `offline`/`error` state with a live unit → run a one-shot health
  probe and adopt the slot into `ready` or `idle` (issue #30).

Routers MUST treat `idle` distinctly from `ready`: an idle slot has no
model advertised and will 4xx on inference attempts (issue #31).

## See also

- [`PLAN.md`](./PLAN.md) — v1 scope, modules ported from haloai, milestones
- [`docs/slots.md`](./docs/slots.md) — slot lifecycle state machine *(TODO)*
- [`docs/dispatcher.md`](./docs/dispatcher.md) — routing algorithm *(TODO)*
- [`docs/install.md`](./docs/install.md) — install flow + filesystem layout *(TODO)*

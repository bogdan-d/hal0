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
│   ├── routes/      # one APIRouter per concern (10 modules)
│   └── middleware/  # error envelope, request id, cors
├── slots/           # slot lifecycle (state machine, unit rendering)
├── dispatcher/      # routing, single-flight, decision logging
├── providers/       # backend abstraction (llama_server, flm, moonshine, kokoro)
├── registry/        # model registry (atomic TOML, mtime cache)
├── hardware/        # probe + stats (GPU, NPU, RAM, disk)
├── upstreams/       # external LLM providers (OpenRouter, etc.)
├── config/          # pydantic schemas, TOML loader, migrations
├── updater/         # self-update (cosign-verified, atomic swap)
├── installer/       # first-run wizard backend, hardware probe writer
├── voice/           # Moonshine + Kokoro provider glue
├── openwebui/       # companion service env file writer
└── cli/             # `hal0` Typer CLI
```

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
  `FLMProvider`, etc.) is a class with `build_env()`, `start_cmd()`,
  `health()`, `infer()`. They don't hold connection state, don't manage
  systemd, and don't share globals. One provider per backend type.
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

## See also

- [`PLAN.md`](./PLAN.md) — v1 scope, modules ported from haloai, milestones
- [`docs/slots.md`](./docs/slots.md) — slot lifecycle state machine *(TODO)*
- [`docs/dispatcher.md`](./docs/dispatcher.md) — routing algorithm *(TODO)*
- [`docs/install.md`](./docs/install.md) — install flow + filesystem layout *(TODO)*

# `hal0-agent@hermes.service` — operator recipes

The Hermes agent runs as a systemd template instance under the
**`hal0-agent@.service`** template. This page covers start/stop/status,
restarts, logs, journals, and the failure modes you'll hit in practice.

For the full Hermes provisioning pipeline (the thing that lays down
`$HERMES_HOME`, `plugins/`, and `runtime.json`) see
[`hermes-bootstrap.md`](../hermes-bootstrap.md). For the chat surface
that consumes the agent's `/api/events` and `/api/pty` streams, see the
v0.3 architecture notes under `docs/internal/`.

## TL;DR

```bash
sudo systemctl start  hal0-agent@hermes.service     # boot
sudo systemctl stop   hal0-agent@hermes.service     # shut down
sudo systemctl status hal0-agent@hermes.service     # one-screen state
sudo journalctl -u    hal0-agent@hermes.service -f  # follow logs
hal0-agent hermes status                            # health-URL probe
```

The unit is **enabled at install time** by `installer/install.sh` after
`hal0 agent bootstrap hermes` runs successfully — you should never have
to enable it by hand.

## What the unit actually runs

`ExecStart=/usr/local/bin/hal0-agent %i serve` where `%i` is the
instance id (`hermes` for this unit). The `hal0-agent` shim then
invokes:

```
/var/lib/hal0/venvs/hermes/bin/hermes dashboard \
  --host 127.0.0.1 --port 9119 \
  --tui --no-open --skip-build
```

The **`dashboard --tui`** subcommand is the only Hermes mode that boots
`hermes_cli/web_server.py`, which is where the `/api/pty`, `/api/events`,
and `/api/ws` endpoints live — the ones hal0's chat surface consumes.

**Do not** rewrite the unit to call `hermes mcp serve`. That mode runs
an MCP query server with no event stream and no PTY; the chat surface
would render blank with no errors.

## Where things live

| Path | What |
|---|---|
| `/etc/systemd/system/hal0-agent@.service` | the template unit |
| `/etc/systemd/system/hal0-agent@hermes.service.d/override.conf` | hermes-specific env |
| `/etc/hal0/agents/hermes.env` (optional) | operator overrides (HERMES_HOME, port, …) |
| `/etc/hal0/agents/hermes.toml` (optional) | shim config (overrides builtin defaults) |
| `/var/lib/hal0/venvs/hermes/` | the agent's venv — `hermes` binary lives in `bin/` |
| `/var/lib/hal0/.hermes/` | `$HERMES_HOME` (config, personas, plugins) |
| `/run/hal0/` | sockets, lock files |
| `/var/log/hal0/` | hal0-side log overflow (most logs go to journald) |

## Lifecycle

### First-boot wiring

`installer/install.sh` (post-bootstrap section) runs:

```
cp installer/systemd/hal0-agent@.service \
   /etc/systemd/system/hal0-agent@.service
mkdir -p /etc/systemd/system/hal0-agent@hermes.service.d
cp installer/systemd/hal0-agent@hermes.service.d/override.conf \
   /etc/systemd/system/hal0-agent@hermes.service.d/override.conf
systemctl daemon-reload
systemctl enable --now hal0-agent@hermes.service
```

The `systemctl enable --now` is gated on `hal0 agent bootstrap hermes`
having completed — if the venv at `/var/lib/hal0/venvs/hermes` isn't
present yet, the shim's `cmd_serve` will bail with a "run bootstrap
first" message and systemd will mark the unit failed (correctly — the
agent has nothing to run).

### Restart / reload

* **Restart** (after editing `override.conf` or upgrading the wheel):
  `sudo systemctl daemon-reload && sudo systemctl restart hal0-agent@hermes.service`
* **Persona reload without restart** (Hermes re-reads
  `overrides.yaml` on `SIGHUP`):
  `sudo systemctl kill -s HUP hal0-agent@hermes.service`
* **Re-provision** (re-render configs, replay bootstrap phases):
  `hal0-agent hermes reprovision` — wraps `hal0 agent bootstrap hermes --repair`.

### Stop

`systemctl stop` sends `SIGTERM`; the shim forwards it to the Hermes
child and waits up to 15s for clean exit (matches `TimeoutStopSec=`).
Beyond that systemd `SIGKILL`s the cgroup.

If `systemctl stop` ever hangs, run `hal0-agent hermes stop` directly —
it scans `/proc` for processes matching the agent's venv binary AND
`HAL0_AGENT_ID=hermes`, SIGTERMs them, then `SIGKILL`s after 10s.

## Health checks

| What | How |
|---|---|
| Is systemd happy? | `systemctl is-active hal0-agent@hermes.service` |
| Is the HTTP surface up? | `hal0-agent hermes status` (probes `http://127.0.0.1:9119/api/health`) |
| Last 60 log lines? | `journalctl -u hal0-agent@hermes.service -n 60 --no-pager` |
| Watchdog trips? | `systemctl show hal0-agent@hermes.service -p NRestarts` |

The unit is `Type=notify` with `WatchdogSec=60`. The shim pings
`WATCHDOG=1` every 25s as long as the child is alive AND
`/api/health` responds. A hung Hermes (alive but unresponsive) trips
the watchdog after 60s and systemd restarts us.

## Failure modes you'll actually hit

### Inference unavailable (`hal0-api` not serving `/v1`)

Hermes reaches inference through `HAL0_INFERENCE_BASE` (default
`http://127.0.0.1:8080`), which is the hal0-api gateway that fronts
the container-runtime inference slots. When chat fails but
`systemctl status hal0-agent@hermes` is green, check that hal0-api is
serving and that at least one inference slot is ready:

```bash
curl -fsS http://127.0.0.1:8080/api/status   # hal0-api up?
hal0 slot list                                # any slot READY?
systemctl restart hal0-api                   # restart hal0-api if down
```

### `hermes binary not found`

The shim refused to start because `/var/lib/hal0/venvs/hermes/bin/hermes`
doesn't exist. Bootstrap was either skipped or failed:

```bash
hal0 agent bootstrap hermes --repair
sudo systemctl restart hal0-agent@hermes.service
```

### Port 9119 already in use

Another hermes (perhaps a manual `hermes dashboard` you forgot about) is
holding the port. Find it:

```bash
ss -tlnp | grep 9119
hal0-agent hermes stop   # SIGTERMs by venv + agent id; ignores other dashboards
```

### Inference base not reachable from the agent

The agent's `HAL0_INFERENCE_BASE` env is wrong (overridden in
`/etc/hal0/agents/hermes.env`) or hal0-api is bound to a different
port/address. The default (`http://127.0.0.1:8080`) matches the
hal0-api bind in `installer/install.sh` — only override if you have
a non-standard layout.

## Customising the unit

**Don't edit `hal0-agent@.service` directly** — `hal0 update` will
overwrite it. Drop overrides in either of:

| File | Scope |
|---|---|
| `/etc/systemd/system/hal0-agent@hermes.service.d/local.conf` | this instance only |
| `/etc/systemd/system/hal0-agent@.service.d/local.conf` | all instances |

Example: bump `WatchdogSec` to 120s for a slow box:

```ini
# /etc/systemd/system/hal0-agent@hermes.service.d/local.conf
[Service]
WatchdogSec=120
```

Then `systemctl daemon-reload && systemctl restart hal0-agent@hermes.service`.

## Adding a new agent instance (v0.4 preview)

The unit is a template — the same file backs `hal0-agent@piccoder.service`
or whatever ships next. Wiring a second instance is just:

1. `hal0 agent install <name>` — provisions venv + `$HERMES_HOME`.
2. (Optional) drop `/etc/hal0/agents/<name>.toml` to override defaults.
3. `systemctl enable --now hal0-agent@<name>.service`.

The shim resolves the agent type from `[type]` in the toml; builtin ids
(`hermes` today) work without a toml.

## Restarting from the dashboard (v0.3 PR-11)

The SidebarAgentBlock service chip wires `POST /api/agents/{id}/restart`,
which is a thin wrapper around `systemctl restart
hal0-agent@{id}.service`. Behaviour:

* Returns `{status: "restarted", detail: "..."}` when systemctl exits
  0 and the unit went through a clean stop-then-start cycle.
* Returns `{status: "restarting", detail: "..."}` when systemctl
  reports the unit is still `activating` (Type=notify hasn't sent
  READY=1 yet). The dashboard's service chip polls after this to
  converge.
* Returns the standard hal0 error envelope when systemctl is missing
  on the host (`agent.systemctl_unavailable`), the subprocess fails
  to spawn (`agent.restart_failed`), or the call exceeds 30s
  (`agent.restart_timeout`).
* Emits an audit row on the `hal0.agents.audit` logger
  (`agent.restart.invoked` → `agent.restart.ok` or
  `agent.restart.failed`). Actor identity comes from `X-hal0-Agent`;
  defaults to `hal0-dashboard` for browser-initiated restarts.

The endpoint is the surface that lets operators trigger a restart
without dropping to SSH. SSH `systemctl restart` still works fine —
this is just the dashboard-friendly path.

## Platform tokens and messaging adapters

The `hal0-agent@hermes.service` unit above is the **dashboard** surface.
The Telegram + Discord **gateway** (the bot that talks to chat apps) runs
as a separate SYSTEM-scope unit, `hermes-gateway.service`, and gets its
platform tokens from a systemd drop-in — NOT a main-unit edit, so the
wiring survives `hermes gateway install` regenerating the main unit.

See [`hermes-gateway-platform-tokens.md`](./hermes-gateway-platform-tokens.md)
for the secrets vault layout, the drop-in at
`/etc/systemd/system/hermes-gateway.service.d/10-hal0-secrets.conf`, the
full key list, and the verification + re-apply runbook. The hal0
provisioner writes that drop-in idempotently in its
`gateway_secrets_wire` phase (issue #437).

## See also

* [`hermes-gateway-platform-tokens.md`](./hermes-gateway-platform-tokens.md) — gateway secrets drop-in (#437)
* [`hermes-bootstrap.md`](../hermes-bootstrap.md) — provisioning state machine
* [`identity.md`](../identity.md) — `X-hal0-Agent` header and auth model
* [`mcp-client.md`](../mcp-client.md) — how Hermes talks to hal0-memory + hal0-admin
* [`CONFIG.md`](./CONFIG.md) — chat surface + hot-reload semantics
* `installer/systemd/hal0-agent@.service` — the unit itself
* `src/hal0/cli/agent_shim.py` — the shim source
* `src/hal0/api/agents/restart.py` — the restart endpoint implementation

# hal0 installer

Non-interactive installer for hal0 — the open-source home AI inference platform.

## Quick start

```sh
# From a clone of this repo:
sudo bash installer/install.sh
```

> **Phase 1 only.** The one-liner `curl -fsSL https://hal0.dev/install | bash`
> will ship once the `hal0.dev/install` endpoint is wired; until then,
> `git clone` + `sudo bash` is the supported entry point.

## What the installer does

1. **Pre-flight checks** — confirms Python 3.11–3.14 is on `$PATH`, systemd is present (skipped in `--dev`), and probes for Docker (a soft warning if missing; slot launches will fail until it's installed).
2. **Privilege model** — runs as `root` (re-execs under `sudo` if needed). The slot template runs the toolbox containers as root by design — the container itself is the sandbox boundary, not the host user. Override with `HAL0_USER=...` if you want a different unit user, but the default is intentional.
3. **Layout** — creates `/opt/hal0/` (code + venv), `/etc/hal0/{,slots}` (config), `/var/lib/hal0/{models,registry,slots,openwebui,cache}` (state). In `--dev` everything lands under `$PWD/.hal0ai/` instead.
4. **Installs hal0** — creates a venv at `/opt/hal0/.venv/` and `pip install -e`'s the checkout into it. There is no versioned install dir or `current` symlink yet — the venv tracks the checkout in editable mode.
5. **Builds the dashboard UI** — runs `npm install && npm run build` in `ui/` if `ui/dist/` is missing and `npm` is available. Skipped (with a warning) when `npm` is absent.
6. **Config defaults** — writes `/etc/hal0/hal0.toml`, `api.env`, `openwebui.env` (rendered by `hal0.openwebui.env_writer`), and slot skeletons for `primary`, `embed`, `stt`, `tts`. Existing files are **never clobbered** on re-run.
7. **systemd units** — writes `hal0-api.service`, copies `hal0-openwebui.service` and `hal0-slot@.service` from `packaging/systemd/` to `/etc/systemd/system/`, reloads the daemon, enables and starts `hal0-api` + `hal0-openwebui` (unless `--no-start`).
8. **Hardware probe + final summary** — prints detected backends and reachable URLs. Skip the probe with `HAL0_NO_PROBE=1`.

The installer is **idempotent** — safe to re-run after a partial failure or to update configuration defaults.

## Environment variables

These are the variables `installer/install.sh` actually reads:

| Variable | Default | Description |
|---|---|---|
| `HAL0_PREFIX` | `/opt/hal0` (or `$PWD/.hal0ai` in `--dev`) | Installation root (venv + code) |
| `HAL0_PORT` | `8080` | hal0 API port |
| `HAL0_USER` | `root` | systemd unit user (see §What the installer does) |
| `HAL0_PYTHON` | `python3` | Python interpreter used to build the venv |
| `HAL0_NO_PROBE` | _(unset)_ | Set to `1` to skip the hardware probe at the end |
| `HAL0_TOOLBOX_IMAGE_VULKAN` | _(unset)_ | Override the Vulkan toolbox image ref written into `api.env` |
| `HAL0_TOOLBOX_IMAGE_ROCM` | _(unset)_ | Override the ROCm toolbox image ref written into `api.env` |
| `HAL0_HOSTNAME` | `hal0.local` | `--auth=basic` only: public hostname used in the Caddyfile |
| `HAL0_TLS_EMAIL` | `admin@$HAL0_HOSTNAME` | `--auth=basic` only: contact email for Let's Encrypt (when not `tls internal`) |
| `HAL0_ADMIN_USER` | _(prompted)_ | `--auth=basic` only: admin username for Caddy basic_auth |
| `HAL0_ADMIN_PASSWORD` | _(prompted)_ | `--auth=basic` only: admin password (hashed by `caddy hash-password`) |
| `HAL0_OPENWEBUI_PORT` † | `3001` | OpenWebUI host port — **dev mode only** |

† `HAL0_OPENWEBUI_PORT` is honored by `scripts/dev-bootstrap.sh` (the dev-mode launcher). The installed `hal0-openwebui.service` hardcodes `:3001`; to change it post-install, edit `/etc/systemd/system/hal0-openwebui.service` and reload.

Example:

```sh
HAL0_PORT=9090 sudo bash installer/install.sh
```

## Authentication (`--auth=basic`)

The default install posture is `--auth=off` — the API binds `:8080` and OpenWebUI binds `:3001` directly, with no auth in front. That's safe on a fully-trusted home LAN; it is **not** safe to expose to the internet.

`--auth=basic` brings up the v0.2 auth POC: a Caddy reverse proxy in front of both services, with HTTP basic_auth at the edge for the dashboard and bearer-token auth for the OpenAI-compatible API.

```sh
# Interactive (prompts for admin user/password):
sudo bash installer/install.sh --auth=basic

# Non-interactive:
HAL0_ADMIN_USER=alex HAL0_ADMIN_PASSWORD='hunter2' \
  HAL0_HOSTNAME=hal0.local \
  sudo bash installer/install.sh --auth=basic
```

What the flag does:

1. Installs Caddy (`apt install caddy` on Debian/Ubuntu, `pacman -S caddy` on Arch/CachyOS). Other distros require a manual install; the script surfaces a clear error and a docs link.
2. Prompts for or accepts via env: `HAL0_ADMIN_USER`, `HAL0_ADMIN_PASSWORD`, `HAL0_HOSTNAME` (default `hal0.local`), `HAL0_TLS_EMAIL` (default `admin@<hostname>`).
3. Hashes the password via `caddy hash-password`, renders `/etc/hal0/Caddyfile` from `packaging/caddy/Caddyfile.template`.
4. Drops `/etc/systemd/system/hal0-caddy.service` and starts it.
5. Sets `HAL0_AUTH_ENABLED=1` in `/etc/hal0/api.env` and re-renders `/etc/hal0/openwebui.env` with `WEBUI_AUTH=True` + `WEBUI_AUTH_TRUSTED_EMAIL_HEADER=X-Forwarded-Email` so OpenWebUI auto-provisions a user from the Caddy-forwarded identity (no second login).
6. Restarts `hal0-api` and `hal0-openwebui` so the new env takes effect.
7. If avahi-daemon is running, drops `/etc/avahi/services/hal0.service` so `hal0.local` resolves on the LAN. Without avahi, add a static `/etc/hosts` entry on each client: `<hal0-ip>  hal0.local`.

After install:

- Dashboard: `https://hal0.local/` — basic_auth prompt → admin user → SPA.
- Chat: `https://hal0.local/chat/` — single-sign-on via the same Caddy basic_auth identity.
- OpenAI API: `https://hal0.local/v1/models` (no auth), `https://hal0.local/v1/chat/completions -H 'Authorization: Bearer hal0_...'` (token required).

Mint a token via the Settings UI (Authentication panel → Create token) or via:

```sh
curl -k -u 'admin:hunter2' \
  https://hal0.local/api/auth/tokens \
  -H 'Content-Type: application/json' \
  -d '{"label": "openwebui-bridge", "scope": "all"}'
```

The raw token is in the response **once** — copy it immediately. To revoke:

```sh
curl -k -u 'admin:hunter2' -X DELETE \
  https://hal0.local/api/auth/tokens/<token-id>
```

The `tls internal` directive in the rendered Caddyfile mints a self-signed certificate via Caddy's internal CA. For a real (DNS-resolvable) hostname, edit `/etc/hal0/Caddyfile` to remove `tls internal` and Caddy will provision a Let's Encrypt cert on the next reload.

To roll back:

```sh
sudo systemctl disable --now hal0-caddy
sudo sed -i 's|^HAL0_AUTH_ENABLED=.*|HAL0_AUTH_ENABLED=0|' /etc/hal0/api.env
sudo HAL0_AUTH_ENABLED=0 /opt/hal0/.venv/bin/python -m hal0.openwebui.env_writer
sudo systemctl restart hal0-api hal0-openwebui
```

## Dev mode (`--dev`)

Runs the full installer logic but lays everything under `$PWD/hal0-home` instead of FHS paths. systemd units are **not** installed or enabled — they are written to `$PWD/hal0-home/etc/systemd/system/` for inspection only.

```sh
bash installer/install.sh --dev
```

Use `scripts/dev-bootstrap.sh` to actually start services during development.

## Uninstall

```sh
# Prompts before deleting config + model data
sudo bash installer/uninstall.sh

# Keep /etc/hal0 and /var/lib/hal0 (models, registry, OpenWebUI state)
sudo bash installer/uninstall.sh --keep-data

# No confirmation prompt (CI / scripted teardown)
HAL0_FORCE=1 sudo bash installer/uninstall.sh
```

## Troubleshooting

### Port already in use

```
✗ pre-flight failed: port 8080 is already in use.
```

Find the process: `lsof -i :8080`  
Then either stop it or re-run with a different port:

```sh
HAL0_PORT=8090 sudo bash installer/install.sh
```

After changing the port, update `/etc/hal0/api.env` and `/etc/hal0/openwebui.env` to match, then `systemctl restart hal0-api hal0-openwebui`.

### Docker not installed

```
✗ pre-flight failed: docker not installed.
```

Install Docker:

```sh
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

### Docker daemon not accessible

```
✗ pre-flight failed: docker daemon not running or not accessible.
```

Start the daemon: `sudo systemctl start docker`  
Or add your user to the docker group and re-login.

### Not enough disk space

```
✗ pre-flight failed: less than 20GB free in /var/lib
```

Free up space, or symlink the models dir to a larger disk before installing:

```sh
mkdir -p /mnt/large-disk/hal0-models
ln -s /mnt/large-disk/hal0-models /var/lib/hal0/models
```

### Services won't start

Check logs:

```sh
journalctl -fu hal0-api
journalctl -fu hal0-openwebui
systemctl status hal0-api hal0-openwebui
```

### OpenWebUI can't reach the API

OpenWebUI is configured to talk to `http://127.0.0.1:8080/v1`. If you changed `HAL0_PORT`, update `/etc/hal0/openwebui.env`:

```
OPENAI_API_BASE_URLS=http://127.0.0.1:<new-port>/v1
```

Then `systemctl restart hal0-openwebui`.

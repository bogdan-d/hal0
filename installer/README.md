# hal0 installer

Non-interactive installer for hal0 — the open-source home AI inference platform.

## Quick start

```sh
# Standard install (requires root/sudo, systemd, Docker, x86_64, ≥20GB free)
curl -fsSL https://hal0.dev/install | bash

# Or from the repo:
sudo bash installer/install.sh
```

## What the installer does

1. **Pre-flight checks** — systemd present, x86_64, Docker accessible, ≥20GB free in `/var/lib`, ports 8080 and 3001 not in use.
2. **System user** — creates `hal0` system user (no shell, no home).
3. **FHS layout** — creates `/usr/lib/hal0/`, `/etc/hal0/slots/`, `/var/lib/hal0/` and subdirs.
4. **Installs hal0** — copies Python package + UI dist into `/usr/lib/hal0/0.0.0-dev/`, symlinks `current →` that dir.
5. **Config defaults** — writes `/etc/hal0/hal0.toml`, `api.env`, `openwebui.env`, and slot skeletons for `primary`, `embed`, `stt`, `tts`. Existing files are **never clobbered** on re-run.
6. **systemd units** — copies `hal0-api.service`, `hal0-openwebui.service`, `hal0-slot@.service` to `/etc/systemd/system/`, reloads daemon, enables and starts `hal0-api` + `hal0-openwebui`.
7. **Prints URLs** and next steps.

The installer is **idempotent** — safe to re-run after a partial failure or to update configuration defaults.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `HAL0_CHANNEL` | `stable` | Update channel (`stable` or `nightly`) |
| `HAL0_AUTO_PULL` | `0` | Pull toolbox + OpenWebUI images on install (Phase 2) |
| `HAL0_INSTALL_DIR` | `/usr/lib/hal0` | Override code installation directory |
| `HAL0_PORT` | `8080` | hal0 API port |
| `HAL0_OPENWEBUI_PORT` | `3001` | OpenWebUI port |

Example:

```sh
HAL0_PORT=9090 HAL0_OPENWEBUI_PORT=3002 sudo bash installer/install.sh
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

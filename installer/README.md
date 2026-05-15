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

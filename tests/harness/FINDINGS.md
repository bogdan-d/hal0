# hal0 test-harness — first-pass findings

Generated 2026-05-15 from a single `bash scripts/harness.sh` run on
hal0-dev (10.0.1.141, RTX 4080, CachyOS). The harness drove every
public surface a developer touches on a fresh install — installer
script, every CLI subcommand, slot lifecycle, settings, uninstall —
and emitted one structured row per scenario into
`tests/harness/reports/harness.json`.

This document is the human-readable companion. Each entry cites a
file:line so a fix can land directly. Severity is **bug** (production
defect), **gap** (missing capability), or **env** (host-side issue,
not a hal0 defect).

Summary of the run: **24 pass, 2 fail, 10 skip, 5 deferred** out of
41 rows.

---

## 1. `hal0 config validate` crashes with ImportError — **bug**

Both `installer` and `cli` tiers caught the same root cause; one
fix kills two rows.

- **Where:** `src/hal0/cli/config_commands.py:76`
- **What:**

  ```python
  from hal0.config.loader import load_hal0_config, load_providers, load_upstreams
  ```

  The names `load_providers` / `load_upstreams` do not exist. The
  loader module (`src/hal0/config/loader.py:315,342`) exports them
  with a `_config` suffix:

  ```python
  def load_providers_config(path: Path | None = None) -> ProvidersConfig:
  def load_upstreams_config(path: Path | None = None) -> UpstreamsConfig:
  ```

- **Symptom:** Every `hal0 config validate` invocation raises
  `ImportError: cannot import name 'load_providers' from
  'hal0.config.loader'` *before* the validator can run.
- **Fix:** rename the imports in `config_commands.py:76, 84, 88` to
  `load_providers_config` / `load_upstreams_config` (or add aliases
  at the bottom of `loader.py`).
- **Impact:** Anyone following the install guide and running
  `hal0 config validate` after first install gets a traceback.

---

## 2. `hal0 slot create` conflates provider and backend — **bug**

The CLI exposes a `--backend` flag whose value is actually the
**provider** (`llama-server`, `flm`, `moonshine`, `kokoro`,
`comfyui`). The slot's **hardware backend** (`vulkan`, `rocm`,
`cpu`, …) is hardcoded.

- **Where:** `src/hal0/cli/slot_commands.py:204–229`
- **What:**

  ```python
  backend: SlotBackend = typer.Option("llama-server", "--backend", "-b", ...)
  ...
  body: dict[str, Any] = {
      ...
      "backend": "vulkan",        # hardcoded
      "provider": str(backend),   # the CLI flag is really the provider
      ...
  }
  ```

- **Symptom:** A user trying to create a ROCm slot via the CLI has
  no way to. The flag they'd reach for (`--backend rocm`) is
  rejected by the SlotBackend enum, which lists provider names not
  hardware targets.
- **Fix options:**
  1. Rename the CLI flag to `--provider` and add a separate
     `--hardware` (default auto-detected from `hardware.json`).
  2. Keep `--backend` but make it accept hardware values, derive
     provider from a separate `--provider` flag.

  Either way, drop the hardcoded `"backend": "vulkan"` on line 228.
- **Impact:** Inability to drive non-Vulkan slots through the CLI;
  workflows that should be one command require hand-editing
  `/etc/hal0/slots/<name>.toml`.

---

## 3. `installer/uninstall.sh` has no `--dev` mode — **gap**

The uninstaller hardcodes FHS paths. If a developer runs it from a
shell where they previously did `bash installer/install.sh --dev`,
it will happily wipe `/etc/hal0`, `/var/lib/hal0`, `/usr/lib/hal0`,
and the systemd units on the actual host.

- **Where:**
  - `installer/uninstall.sh:95-107` (units in `/etc/systemd/system`)
  - `installer/uninstall.sh:113-120` (`/usr/lib/hal0`)
  - `installer/uninstall.sh:153-160` (`/etc/hal0`, `/var/lib/hal0`)
- **What's missing:** a `--dev` (or `HAL0_PREFIX=…`) path that
  mirrors `install.sh:89–100`'s dev-mode layout so the uninstaller
  only touches the prefix.
- **Workaround the harness uses:** `harness-cleanup.sh:dev-manual-cleanup`
  does the rm-rf by hand, never invoking `uninstall.sh` in dev mode.
- **Fix:** add `--dev` to `uninstall.sh`. Compute `PREFIX`, `ETC_DIR`,
  `VAR_DIR`, `UNIT_DIR` exactly like `install.sh:89–100` and use
  those in the rm loops.
- **Impact:** dev-mode round-trip incomplete; can hurt operators
  who copy/paste guide snippets.

---

## 4. `installer/uninstall.sh` doesn't remove `hal0-caddy.service` — **bug**

- **Where:** `installer/uninstall.sh:96–99`

  ```bash
  for UNIT_FILE in \
      "${UNIT_DIR}/hal0-api.service" \
      "${UNIT_DIR}/hal0-openwebui.service" \
      "${UNIT_DIR}/hal0-slot@.service"
  do
  ```

  The fourth unit installed by `--auth=basic` (`hal0-caddy.service`,
  written by `install.sh:439`) is missing from the loop.
- **Symptom:** After `install.sh --auth=basic` + `uninstall.sh`,
  `systemctl status hal0-caddy` still shows an enabled unit (failed
  to start, since the binary it points at is gone). The next
  `systemctl daemon-reload` warns about the orphan.
- **Fix:** add `"${UNIT_DIR}/hal0-caddy.service"` to the list.

---

## 5. `installer/systemd/` is dead code — **gap**

- **Files shipped but unused:**
  - `installer/systemd/hal0-api.service`
  - `installer/systemd/hal0-slot@.service`
- **Evidence:**
  - `installer/install.sh:488` writes the API unit *inline* with `cat >`
  - `installer/install.sh:512` reads the slot template from
    `${REPO_ROOT}/packaging/systemd/hal0-slot@.service`, not from
    `installer/systemd/`.
- **Risk:** if someone edits `installer/systemd/hal0-slot@.service`
  intending to ship a fix, nothing changes — the installer reads
  the file in `packaging/systemd/` instead.
- **Fix options:**
  1. Delete `installer/systemd/`.
  2. Move both template units there and rewire `install.sh:512` and
     the inline cat at 488 to copy from this directory.

---

## 6. Slots created under `--dev` can't actually start — **gap**

- **Where:**
  - `installer/install.sh:530-533` skips `systemctl daemon-reload` in
    `--dev` mode.
  - The units are written to `${PREFIX}/etc/systemd/system/` but the
    host's `systemctl` only consults `/etc/systemd/system` and
    `/usr/lib/systemd/system`.
- **Symptom:** `hal0 slot create … && hal0 slot load …` succeeds
  through slot create, but `slot load` fails with "Unit
  hal0-slot@<name>.service not found." The harness's `runtime-slot-load`
  row would surface this as `fail` if a toolbox image were available.
- **Fix options (rank from least invasive to most):**
  1. Document the limitation in `installer/README.md` and have
     `--dev` print a warning.
  2. Use `systemctl --user` units instead of system units in `--dev`
     mode (changes the entire deployment story for dev installs).
  3. Provide a parallel non-systemd launcher (`hal0 slot launch` is
     already a binary at `installer/bin/hal0-slot-launch`) that
     `--dev` mode wires up.
- **Impact:** The "polished one-line install for home users" goal
  is fine, but the dev-loop story has a sharp edge that the v1
  contributor docs need to call out.

---

## 7. `releases.hal0.dev` is not reachable — **env / gap**

- **Where:** `hal0 update --check` calls
  `GET /api/updates/check`, which fetches `https://releases.hal0.dev/stable.json`.
- **Observation:** the host can't resolve `releases.hal0.dev`
  (`[Errno -5] No address associated with hostname`). The API
  returns HTTP 500 correctly; the CLI surfaces the upstream error.
- **Fix path:** stand up `releases.hal0.dev` as part of the v1
  release ritual, OR ship the URL as configurable so home installs
  can point at a self-hosted manifest.
- **Note:** the harness marks this as `deferred`, not `fail`, since
  the CLI behaviour is correct given the missing infra.

---

## 8. `ghcr.io/hal0ai/*` toolbox images return `unauthorized` — **env / gap**

- **Observation:** `docker pull ghcr.io/hal0ai/hal0-toolbox-vulkan:v1`
  (and pulling by digest from `manifest.json`) returns
  `Error response from daemon: error from registry: unauthorized`.
- **Memory says:** "all images are published" (per the user note).
- **Reality on hal0-dev:** can't pull without auth. Either:
  - The packages are private and `docker login ghcr.io -u <user> -t <PAT>`
    is needed (and that should be a documented installer prerequisite),
    OR
  - The image refs in `manifest.json` are wrong (mismatched org or
    tag), OR
  - The org's package visibility setting hasn't been flipped to
    public yet.
- **Impact:** every `runtime-*` row in the harness skipped on the
  dev box; release-gate γ on hal0-test LXC may also fail to pull on
  a clean reinstall.
- **Action:** verify visibility on ghcr.io/hal0ai/* packages, or
  document the login requirement in `installer/README.md` (and have
  `install.sh` warn if a docker config token isn't present).

---

## 9. host `/` filesystem at 96% on hal0-dev — **env**

`hal0 doctor` correctly fails because `/var/lib` lives on the same
74 GB root partition that's now at 3.6 GB free.

This is not a hal0 defect — it's a heads-up for the operator. The
harness's `cli-doctor` row reports it as `deferred` so it doesn't
hide a real regression.

Recommended host fix: bind-mount `/var/lib/hal0` (or set
`HAL0_PREFIX` to a path on the larger `/devpool` / `/mnt/...`
volumes) before next install.

---

## What the harness *didn't* try (and why)

| Path | Reason | How to enable |
|---|---|---|
| `install.sh` prod install (touches `/etc`, `/var/lib`, `/usr/lib`) | mutates the real host | `HAL0_HARNESS_PROD=1 bash scripts/harness.sh` |
| `--auth=basic` Caddy install | needs prod mode + caddy installable | `HAL0_HARNESS_AUTH=1 HAL0_HARNESS_PROD=1 …` |
| ROCm / FLM-NPU / Moonshine / Kokoro real-model rounds | `hal0-test` LXC owns these | `make release-test` (existing γ tier) |
| Settings GET/PUT round-trip | route exists but not driven; planned next harness iteration | extend `cli-test.sh` |
| First-run wizard endpoints | currently mostly stub (PLAN §7) | wait for Team-B model-pull integration |
| Update --apply / --rollback | needs working releases.hal0.dev | unblock #7 above |

---

## How to re-run

```
# full harness (no prod, no auth):
bash scripts/harness.sh

# include sudo /opt/hal0 install + uninstall:
HAL0_HARNESS_PROD=1 bash scripts/harness.sh

# include --auth=basic install path too:
HAL0_HARNESS_AUTH=1 HAL0_HARNESS_PROD=1 bash scripts/harness.sh
```

The aggregate JSON lands at `tests/harness/reports/harness.json` and
the pretty-printed table is dumped to stdout at the end of every
run.

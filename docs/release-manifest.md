# hal0 release manifest schema (`hal0.releases.v1`)

The release manifest is a single JSON file served per channel at:

```
https://releases.hal0.dev/{stable|nightly}.json
```

`hal0 update --check` (CLI) and `GET /api/updates/check` (API) both fetch
this file, validate it against the schema below, and compare
`version` against `hal0.__version__`. `hal0 update` (no `--check`)
additionally downloads the tarball + cosign signature, verifies both,
extracts to `/usr/lib/hal0-<version>/`, and atomically swaps the
`/usr/lib/hal0/current` symlink.

The publisher (the `release.yml` GitHub Actions workflow) produces this
file post-build; the runtime consumer is `hal0.updater.Updater.apply()`.

## Schema

```json
{
  "_schema": "hal0.releases.v1",
  "version": "0.1.1",
  "channel": "stable",
  "url": "https://github.com/hal0-dev/hal0/releases/download/v0.1.1/hal0-0.1.1.tar.gz",
  "sig_url": "https://github.com/hal0-dev/hal0/releases/download/v0.1.1/hal0-0.1.1.tar.gz.sig",
  "digest_sha256": "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",
  "signer_identity": "^https://github\\.com/hal0-dev/hal0/\\.github/workflows/release\\.yml@refs/tags/v0\\.1\\.1$",
  "signer_issuer": "https://token.actions.githubusercontent.com",
  "min_data_version": 1,
  "released_at": "2026-05-15T12:00:00Z",
  "notes_url": "https://github.com/hal0-dev/hal0/releases/tag/v0.1.1",
  "manifest_url": "https://releases.hal0.dev/stable.json",
  "toolbox_images": {
    "vulkan": { "tag": "ghcr.io/hal0-dev/hal0-toolbox-vulkan:v0.1.1", "digest": "sha256:..." },
    "rocm":   { "tag": "ghcr.io/hal0-dev/hal0-toolbox-rocm:v0.1.1",   "digest": "sha256:..." },
    "flm":    { "tag": "ghcr.io/hal0-dev/hal0-toolbox-flm:v0.1.1",    "digest": "sha256:..." }
  }
}
```

### Field reference

| Field | Type | Required | Notes |
|---|---|---|---|
| `_schema` | string | yes | Always `"hal0.releases.v1"`. Bump when the shape changes. |
| `version` | string | yes | Dotted release version (no leading `v`). |
| `channel` | string | no | `"stable"` (default), `"nightly"`, `"dev"`. |
| `url` | string | yes | `http(s)` or `file://` URL of the release tarball. |
| `sig_url` | string | yes | URL of the detached cosign signature (`*.sig`). |
| `digest_sha256` | string | yes | Hex sha256 of the tarball bytes (64 chars). `sha256:` prefix tolerated. |
| `signer_identity` | string | yes | Regex passed to `cosign verify-blob --certificate-identity-regexp`. Must anchor (`^...$`) to the exact GH Actions workflow + ref. |
| `signer_issuer` | string | no | OIDC issuer; defaults to GitHub Actions (`token.actions.githubusercontent.com`). |
| `min_data_version` | int | no | Smallest acceptable `meta.schema_version` on disk. Updater runs forward migrations up to `max(min_data_version, latest_version())`. Default `1`. |
| `released_at` | string | no | ISO-8601 release timestamp; surfaced in the dashboard. |
| `notes_url` | string | no | Link to release notes. |
| `manifest_url` | string | no | Self-reference (so a cached copy knows where it came from). |
| `toolbox_images` | object | no | Mirrors the in-tree `manifest.json` shape: `{name: {tag, digest}}`. The release pins compatible container images. |

Pydantic enforces shape at fetch time
(`hal0.updater.updater._parse_manifest`). Malformed manifests reject
with `system.update_manifest_invalid` and the update flow stops before
the first byte is downloaded.

## Cosign verification

The updater shells out to `cosign verify-blob`:

```
cosign verify-blob \
  --signature <sig_url-payload> \
  --certificate-identity-regexp <signer_identity> \
  --certificate-oidc-issuer    <signer_issuer> \
  <tarball-path>
```

If `cosign` is not on `PATH` the updater raises a typed error
(`system.update_cosign_missing`) with install hints. It does **not**
fall back to unsigned acceptance.

### Documented gap: `HAL0_UPDATE_SKIP_COSIGN`

For the Phase-2 prototype + LXC smoke (PLAN §17 risk #2 — "prototype in
phase 2 against a throwaway release, not phase 5"), setting
`HAL0_UPDATE_SKIP_COSIGN=1` bypasses the verify step with a loud WARN
log. This gap **must close before v1 ships** — the production install
path on `hal0.dev` must produce a real GH-Actions-signed artifact, and
the env var must be removed (or hard-fail) in `release/v1.0.0`.

## Filesystem effects of `apply()`

```
# Before
/usr/lib/hal0/
  current -> /usr/lib/hal0-0.1.0/
  hal0-0.1.0/

/var/lib/hal0/
  cache/                 (may be absent)
  hal0.previous          (may be absent — first install)

# After hal0 update to 0.1.1
/usr/lib/hal0/
  current -> /usr/lib/hal0-0.1.1/   (atomic swap)
  hal0-0.1.0/                       (retained for rollback)
  hal0-0.1.1/                       (newly extracted)

/var/lib/hal0/
  cache/0.1.1/
    hal0-0.1.1.tar.gz
    hal0-0.1.1.tar.gz.sig
  hal0.previous          (content: "/usr/lib/hal0-0.1.0")
```

`hal0 update --rollback` reads `/var/lib/hal0/hal0.previous`, swaps the
symlink back, and re-points the previous record at what was just
current — so a second rollback bounces between the two installs.

## What the release pipeline must guarantee

When `hal0.dev` exists and the `release.yml` workflow runs, it must:

1. Build `hal0-<version>.tar.gz` as a tar archive with a top-level
   `hal0-<version>/` directory (matches the synthetic-prototype shape
   used by the tests and the LXC smoke).
2. Compute `digest_sha256` of the tarball bytes (no compression-format
   ambiguity — sha the on-disk file).
3. Sign with cosign keyless against the workflow's OIDC identity. The
   `signer_identity` in the manifest must anchor exactly to that
   identity (`^https://github.com/<org>/<repo>/.github/workflows/release.yml@refs/tags/v<ver>$`).
4. Publish `hal0-<version>.tar.gz` + `.sig` as release assets.
5. POST/commit the new `stable.json` or `nightly.json` to whatever
   serves `releases.hal0.dev`. Stable releases supersede the prior
   `stable.json` atomically — the updater fetches whatever's there.
6. Patch `toolbox_images.<name>.digest` with the sha256 content digests
   from the toolbox build (`toolbox.yml` already does this for
   `manifest.json`; mirror that block into the release manifest so an
   update pulls the exact image set known-good for that release).

## Related

- `PLAN.md` §9 — Update mechanism spec
- `PLAN.md` §17 risk #2 — cosign edge cases
- `src/hal0/updater/updater.py` — implementation
- `src/hal0/api/routes/updater.py` — route layer (Team C)
- `manifest.json` — toolbox image pin file (Team A)

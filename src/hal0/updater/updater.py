"""Self-update mechanism for hal0.

Updater handles the full update lifecycle:
  1. Check hal0.dev/releases/latest.json for a newer version
  2. Download tarball + cosign signature
  3. Verify the signature against the hal0-dev/hal0 GitHub OIDC identity
  4. Extract to /usr/lib/hal0-<new>/
  5. Run pending config migrations (hal0.config.migrate)
  6. Atomic-swap the /usr/lib/hal0/current symlink
  7. systemctl restart hal0-api (slots untouched)
  8. Retain the old version for rollback

Rollback swaps the symlink back and restarts the API.

Port target: haloai lib/updater.py (569 lines).
Note: depends on cosign + signed releases (must exist before Phase 5 work
begins). The route layer at ``hal0.api.routes.updater`` consumes the
signatures here, so the surface is real even before Team D fills in
semantics — every method below raises ``NotImplementedError`` with a
clear hand-off message.

See PLAN.md §9 (update mechanism) and §5 Phase 5 milestone.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_RELEASES_URL = "https://releases.hal0.dev/latest.json"


def releases_url(channel: str = "stable") -> str:
    """Return the release-manifest URL for ``channel``.

    Honours the ``HAL0_RELEASES_URL`` env var so tests + dev installs can
    point at a local file (``file:///tmp/latest.json``) or a fake HTTP
    endpoint without patching the source. The default points at the
    production manifest.
    """
    override = os.environ.get("HAL0_RELEASES_URL", "").strip()
    base = override or DEFAULT_RELEASES_URL
    # The manifest is per-channel in production; tests use a single
    # static file, so don't rewrite the URL when an override is set.
    if override:
        return base
    if channel and channel != "stable":
        # Append ?channel=nightly to the default so the production
        # release service can shard manifests per channel.
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}channel={channel}"
    return base


async def fetch_release_manifest(channel: str = "stable") -> dict[str, Any]:
    """Fetch and parse the release manifest for ``channel``.

    Returns the parsed JSON dict. Supports both ``http(s)://`` URLs (via
    httpx) and ``file://`` URLs / bare paths (for tests). Raises
    ``OSError`` on transport failures and ``ValueError`` on bad JSON so
    callers can produce typed envelopes.
    """
    url = releases_url(channel)
    parsed = urlparse(url)
    if parsed.scheme in ("", "file"):
        # bare path or file:// — read from disk.
        path = parsed.path if parsed.scheme == "file" else url
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise OSError(f"could not read release manifest at {path}: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"release manifest at {path} is not valid JSON: {exc}") from exc

    # http(s) — defer httpx import so the file path stays dependency-free
    # during tests that don't touch the network.
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        # httpx ConnectError / TimeoutException / etc. — surface as OSError
        # so the route's existing handler renders the typed envelope.
        raise OSError(f"release manifest fetch failed for {url}: {exc}") from exc
    if resp.status_code != 200:
        raise OSError(f"release manifest fetch returned HTTP {resp.status_code} from {url}")
    try:
        return resp.json()
    except ValueError as exc:
        raise ValueError(f"release manifest at {url} is not valid JSON: {exc}") from exc


class Updater:
    """Atomic self-update with cosign-verified releases and one-step rollback.

    All methods are async; call from asyncio context or via asyncio.run().
    The class is a stable seam — the API route layer calls these methods
    so Team D can fill in the real semantics without changing the route
    contract.
    """

    def __init__(self, channel: str = "stable") -> None:
        """Initialise the updater.

        Args:
            channel: Release channel — "stable" (default) or "nightly".
        """
        self.channel = channel

    async def check(self) -> dict[str, Any]:
        """Check for a newer version on the configured release channel.

        Returns a dict with keys:
            update_available (bool)
            current_version (str)
            latest_version (str | None)
            release_url (str | None)

        The route layer prefers ``fetch_release_manifest`` directly for
        the GET /api/updates/check path so the response shape matches the
        manifest verbatim; this instance method is the CLI-side caller.

        Raises:
            NotImplementedError: Until Phase 5 (Team D's port).
        """
        raise NotImplementedError(
            "Phase 5: port from /opt/haloai/lib/updater.py — depends on cosign + signed releases"
        )

    async def apply(self, version: str | None = None) -> None:
        """Download, verify, install, and activate ``version`` (or latest).

        Drives the real update flow: download tarball + sig, cosign-verify,
        extract to /usr/lib/hal0-<new>/, run config migrations, atomic-swap
        the /usr/lib/hal0/current symlink, restart hal0-api.

        Args:
            version: Specific version to install, or None to use latest.

        Raises:
            NotImplementedError: Until Phase 5 (Team D's port).
        """
        raise NotImplementedError(
            "Phase 5: port from /opt/haloai/lib/updater.py — depends on cosign + signed releases"
        )

    # Backwards-compat alias for the CLI; new callers should prefer apply().
    async def pull(self, version: str | None = None) -> None:
        await self.apply(version)

    async def rollback(self) -> None:
        """Revert to the previously installed version.

        Swaps /usr/lib/hal0/current back to the retained old version dir
        and restarts hal0-api.

        Raises:
            NotImplementedError: Until Phase 5 (Team D's port).
        """
        raise NotImplementedError(
            "Phase 5: port from /opt/haloai/lib/updater.py — depends on cosign + signed releases"
        )

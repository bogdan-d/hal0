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
Note: depends on cosign + signed releases (must exist before Phase 5 work begins).
See PLAN.md §9 (update mechanism) and §5 Phase 5 milestone.
"""

from __future__ import annotations

from typing import Any


class Updater:
    """Atomic self-update with cosign-verified releases and one-step rollback.

    All methods are async; call from asyncio context or via asyncio.run().
    """

    def __init__(self, channel: str = "stable") -> None:
        """Initialise the updater.

        Args:
            channel: Release channel — "stable" (default) or "nightly".
        """
        self.channel = channel

    async def check(self) -> dict[str, Any]:
        """Check for a newer version on the configured release channel.

        Fetches hal0.dev/releases/latest.json and compares against the
        installed version.

        Returns a dict with keys:
            update_available (bool)
            current_version (str)
            latest_version (str | None)
            release_url (str | None)

        Raises:
            NotImplementedError: Until Phase 5.
        """
        raise NotImplementedError(
            "Phase 5: port from /opt/haloai/lib/updater.py — depends on cosign + signed releases"
        )

    async def pull(self, version: str | None = None) -> None:
        """Download, verify, install, and activate a new version.

        Args:
            version: Specific version to install, or None to use latest.

        Raises:
            NotImplementedError: Until Phase 5.
        """
        raise NotImplementedError(
            "Phase 5: port from /opt/haloai/lib/updater.py — depends on cosign + signed releases"
        )

    async def rollback(self) -> None:
        """Revert to the previously installed version.

        Swaps /usr/lib/hal0/current back to the retained old version dir
        and restarts hal0-api.

        Raises:
            NotImplementedError: Until Phase 5.
        """
        raise NotImplementedError(
            "Phase 5: port from /opt/haloai/lib/updater.py — depends on cosign + signed releases"
        )

"""Feature flags store.

FeatureFlags reads from and writes to the [features] section of hal0.toml
(or a dedicated features.toml).  Used by the Settings API route and the
hal0 CLI.

Port target: haloai lib/features.py.
See PLAN.md §3.
"""

from __future__ import annotations

from typing import Any


class FeatureFlags:
    """Read/write feature flag store backed by hal0.toml [features].

    All get/set operations go through this class so that flag access is
    auditable and future migrations (e.g. moving a flag to a dedicated
    section) are centralised.
    """

    def get(self, flag: str, default: Any = None) -> Any:
        """Return the value of a feature flag.

        Args:
            flag:    Feature flag name, e.g. "enable_npu".
            default: Value to return if the flag is not set.

        Raises:
            NotImplementedError: Until Phase 1 port from haloai lib/features.py.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/features.py")

    def set(self, flag: str, value: Any) -> None:
        """Set a feature flag value.

        Writes atomically to the config file.

        Args:
            flag:  Feature flag name.
            value: New value (must be TOML-serialisable).

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/features.py")

    def all(self) -> dict[str, Any]:
        """Return all feature flags as a dict.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/features.py")

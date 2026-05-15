"""UpstreamRegistry — registry of HTTP upstream targets.

An Upstream is one routing target that speaks OpenAI-compatible HTTP (or
close enough for the Dispatcher's forwarding layer).

Two kinds:
  - "slot"    — local inference container managed by SlotManager.
                Eligible for on-demand warmup.
  - "remote"  — external HTTP endpoint (OpenRouter, Anthropic, OpenAI, custom).
                Lifecycle is owned elsewhere.

Loaded from /etc/hal0/upstreams.toml plus auto-registered slots.  The TOML
wins for any slot that's explicitly listed; missing slots get auto-populated
from configured slot names and their ports.

Port target: haloai lib/upstreams.py (737 lines).
Adds: adaptive cold-boot timeout (PLAN.md §5 Tier 1).
See PLAN.md §3 and §5 Tier 1 ("cold-boot health probe … exponential backoff").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_DEFAULT_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True)
class Upstream:
    """One routing target.  Frozen — mutable state lives in UpstreamRegistry caches.

    Mirrors haloai lib/upstreams.py::Upstream, adapted for hal0 naming and
    the hal0.config.paths path resolver.
    """

    name: str
    """Unique name within this registry, e.g. "primary" or "openrouter"."""

    kind: str
    """Target kind: "slot" | "remote"."""

    url: str
    """Base URL, e.g. "http://127.0.0.1:8081/v1" or "https://openrouter.ai/api/v1"."""

    auth_style: str = "bearer"
    """How to present the API key: "bearer" | "anthropic" | "google_query" | "header" | "none"."""

    auth_header: str = ""
    """Custom header name when auth_style == "header"."""

    auth_value_env: str = ""
    """Environment variable holding the API key credential.  Never stored in TOML."""

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    """Total request timeout for this upstream.  0 means use the global default."""

    slot_name: str | None = None
    """Set when kind == "slot".  Must match a configured slot name."""

    warmup_strategy: str = "none"
    """On-demand warmup policy: "none" | "ondemand" | "always"."""

    health_path: str = "/health"
    """Path for health checks, relative to url."""

    ttl_warmup_seconds: float = 30.0
    """Warmup grace period when warmup_strategy == "ondemand"."""

    advertise_models: bool = True
    """Whether to include this upstream's /v1/models in aggregated model list."""

    # NOTE: revisit in Phase 3 — adaptive cold-boot interval config goes here
    # (PLAN.md §5 Tier 1: probe intervals 0.5s, 1s, 2s, 5s, 10s; total grace 180s)


class UpstreamRegistry:
    """Registry of all routing targets (slots + remote upstreams).

    Loaded at startup from /etc/hal0/upstreams.toml and kept in memory.
    Supports dynamic registration for auto-discovered slots.
    """

    def __init__(self) -> None:
        self._upstreams: dict[str, Upstream] = {}

    def list(self) -> list[Upstream]:
        """Return all registered upstreams.

        Raises:
            NotImplementedError: Until Phase 1 port from haloai lib/upstreams.py.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/upstreams.py")

    def get(self, name: str) -> Upstream | None:
        """Return an upstream by name, or None if not found.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/upstreams.py")

    def add(self, upstream: Upstream) -> None:
        """Register a new upstream.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/upstreams.py")

    def remove(self, name: str) -> bool:
        """Remove an upstream by name.  Returns True if it was present.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/upstreams.py")

    async def test(self, name: str) -> dict[str, Any]:
        """Test reachability and auth for an upstream.

        Returns a dict with keys: ok (bool), status (str), latency_ms (float).

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/upstreams.py")

    async def fetch_models(self, name: str) -> list[str]:
        """Fetch available model ids from an upstream's /v1/models.

        Returns an empty list if the upstream doesn't support model listing.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/upstreams.py")

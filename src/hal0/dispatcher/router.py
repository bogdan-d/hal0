"""Dispatcher — registry-aware request router.

The Dispatcher reads the model registry and upstream list to decide where
to forward each OpenAI-compatible request.  It does not start or stop slots;
if a slot is offline, it returns a structured dispatch error and leaves slot
management to the caller.

Resolution order (per PLAN.md §1 and haloai lib/dispatcher.py):
  1. Exact registry binding: request.model → registered slot/upstream
  2. Provider fallback: cold-cache prefetch, single-flight coalescing
  3. Upstream fallback: remote upstream if all local slots are busy/offline
  4. Error: no route found → {"error": {"code": "dispatch.no_route", ...}}

Decision logging: every routing decision emits one structured log line with
{request_id, model, resolution_path, upstream, cache_state, latency_ms}
to journald with SYSLOG_IDENTIFIER=hal0-dispatch (PLAN.md §5 Tier 2).

Port target: haloai lib/dispatcher.py (617 lines).
See PLAN.md §3 and §5 Tier 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hal0.upstreams.registry import UpstreamRegistry

if TYPE_CHECKING:
    from fastapi import Request


@dataclass
class UpstreamCall:
    """A fully-resolved routing decision ready to be forwarded.

    Mirrors the shape in haloai lib/dispatcher.py, adapted for hal0's
    typed Upstream model.

    All fields are set before the Dispatcher returns; callers must not
    mutate this object.
    """

    upstream_name: str
    """Name of the selected upstream (slot name or remote provider id)."""

    target_url: str
    """Fully-qualified URL to forward the request to, including path."""

    headers: dict[str, str] = field(default_factory=dict)
    """Auth and content headers to inject before forwarding."""

    body: bytes = b""
    """Re-encoded request body (may differ from original if model was remapped)."""

    streaming: bool = False
    """Whether the upstream response should be streamed."""

    method: str = "POST"
    """HTTP method to use when forwarding."""

    resolved_model: str = ""
    """Model identifier as the upstream expects it (may differ from requested_model)."""

    requested_model: str = ""
    """Original model field from the client request body."""

    resolution_path: str = ""
    """Debug breadcrumb describing how this routing decision was made.

    Examples: "registry.exact", "registry.fallback", "upstream.remote".
    """

    latency_ms: float = 0.0
    """Time spent in routing logic (not including the upstream round-trip)."""


class Dispatcher:
    """Routes incoming OpenAI-compatible requests to an upstream or slot.

    Instantiated once in the API lifespan and injected via Depends().
    Thread/async-safe: all state is either immutable or protected by asyncio
    locks inside UpstreamRegistry.
    """

    def __init__(self, upstream_registry: UpstreamRegistry | None = None) -> None:
        self._upstreams = upstream_registry or UpstreamRegistry()
        # NOTE: prefetch_timeout_s is configurable (PLAN.md §5 Tier 2, default 8s)
        self.prefetch_timeout_s: float = 8.0

    async def dispatch(self, request: Request, body: dict[str, Any] | None = None) -> UpstreamCall:
        """Resolve a request to an UpstreamCall.

        Args:
            request: The incoming FastAPI Request object.
            body:    Parsed JSON body dict.  If None, the body will be read
                     from request.body() internally.

        Returns:
            A populated UpstreamCall ready for forwarding.

        Raises:
            NotImplementedError: Until Phase 1 port from haloai lib/dispatcher.py.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/dispatcher.py")

    async def forward(self, call: UpstreamCall) -> Any:
        """Execute the HTTP forward and return a FastAPI Response.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/dispatcher.py")

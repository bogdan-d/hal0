"""Legacy proxy fallback for the dispatcher.

Kept during Phase 1 as a compatibility shim while lib/proxy.py from haloai
is being ported into the Dispatcher proper.  PLAN.md notes this will be
absorbed into router.py post-v0.2 and this file deleted.

Port target: haloai lib/proxy.py.
See PLAN.md §3 (module port plan — "keep for now; absorbed into router post-v0.2").
"""

from __future__ import annotations

# NOTE: revisit in Phase 5 — absorb into router.py after Dispatcher is stable


def resolve_slot(path: str, model_id: str) -> str | None:
    """Resolve a request path + model_id to a slot base URL.

    Returns the slot base URL (e.g. "http://127.0.0.1:8081") if a matching
    slot is running and ready, or None to signal that no local slot can
    serve this request.

    This is the fallback path in Dispatcher.dispatch() when the registry
    lookup yields no direct binding.

    Args:
        path:     The original request path (e.g. "/v1/chat/completions").
        model_id: The model field from the request body.

    Returns:
        A slot base URL string, or None.

    Raises:
        NotImplementedError: Until Phase 1 port from haloai lib/proxy.py.
    """
    raise NotImplementedError("Phase 1: port from /opt/haloai/lib/proxy.py")

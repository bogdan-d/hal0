"""Request coalescing / single-flight for cold-cache prefetch.

When multiple concurrent requests trigger a cold-cache prefetch for the same
(upstream, operation) pair, SingleFlightGroup ensures only one HTTP call is
made.  All other waiters share the result.  On error, all waiters receive
the same error without triggering a retry storm.

This is a Tier 3 reliability item per PLAN.md §5.  The in-flight map is
keyed by (upstream_name, operation) where operation is typically the model ID
or the endpoint being prefetched.

Design notes:
  - Uses asyncio.Future so that waiters are scheduled on the event loop
    without polling.
  - No timeout inside SingleFlightGroup itself — callers wrap in asyncio.wait_for.
  - Thread-safety: only call from async context (the FastAPI event loop).
    If sync routes need this, they must delegate via asyncio.run_coroutine_threadsafe.

See PLAN.md §5 Tier 3 ("Request coalescing / single-flight").
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class SingleFlightGroup:
    """Coalesces concurrent calls with the same key into a single in-flight request.

    Usage::

        group = SingleFlightGroup()

        result = await group.do("my-key", some_async_fn, arg1, arg2)

    If "my-key" is already in-flight, this awaitable suspends until the
    original call resolves, then returns (or raises) the same value/exception.
    """

    def __init__(self) -> None:
        # Maps key → asyncio.Future that resolves to the call's result.
        self._inflight: dict[str, asyncio.Future[Any]] = {}

    async def do(
        self,
        key: str,
        fn: Callable[..., Coroutine[Any, Any, T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute fn(*args, **kwargs) for key, or wait for the in-flight call.

        Args:
            key:    Deduplication key, e.g. f"{upstream_name}:{model_id}".
            fn:     Async callable to invoke if key is not in-flight.
            *args:  Positional arguments for fn.
            **kwargs: Keyword arguments for fn.

        Returns:
            The return value of fn.

        Raises:
            Any exception raised by fn — shared to all waiters.
            NotImplementedError: Until Phase 5 implementation.
        """
        raise NotImplementedError("Phase 5: implement single-flight coalescing (PLAN.md §5 Tier 3)")

    def in_flight_keys(self) -> list[str]:
        """Return a snapshot of currently in-flight keys (for diagnostics)."""
        raise NotImplementedError("Phase 5: implement single-flight coalescing (PLAN.md §5 Tier 3)")

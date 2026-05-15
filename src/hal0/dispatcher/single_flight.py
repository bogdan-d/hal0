"""Request coalescing / single-flight for cold-cache prefetch.

When multiple concurrent requests trigger a cold-cache prefetch for the same
(upstream, operation) pair, SingleFlightGroup ensures only one HTTP call is
made.  All other waiters share the result.  On error, all waiters receive
the same error without triggering a retry storm.

This is a Tier 3 reliability item per PLAN.md §5.  The in-flight map is
keyed by an opaque string (typically ``f"{upstream_name}:{model_id}"`` or
``f"{upstream_name}:fetch_models"``).

Design notes:
  - Uses asyncio.Future so that waiters are scheduled on the event loop
    without polling.
  - No timeout inside SingleFlightGroup itself — callers wrap in asyncio.wait_for.
  - Thread-safety: only call from async context (the FastAPI event loop).
    If sync routes need this, they must delegate via asyncio.run_coroutine_threadsafe.
  - Re-entrancy: the leader runs ``fn`` directly (no extra task), so any
    exception (including ``CancelledError``) is set on the shared Future
    and re-raised to every waiter.

See PLAN.md §5 Tier 3 ("Request coalescing / single-flight").
"""

from __future__ import annotations

import asyncio
import contextlib
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

    async def do(  # TIER3
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
        """
        # NOTE: Fast path — an existing in-flight Future for this key means
        # we are a follower and just wait on the leader's result.  This is
        # the entire point of single-flight: one upstream call, many waiters.
        existing = self._inflight.get(key)
        if existing is not None:
            return await existing  # type: ignore[no-any-return]

        # We are the leader.  Install the future BEFORE awaiting fn so that
        # any concurrent callers awaiting the event loop see us as in-flight.
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        self._inflight[key] = future
        try:
            result = await fn(*args, **kwargs)
        except BaseException as exc:  # TIER3 — share the exception with every waiter
            # NOTE: catch BaseException so CancelledError and KeyboardInterrupt
            # also propagate identically to followers.  We don't swallow it.
            if not future.done():
                future.set_exception(exc)
            # Mark the future "consumed" if no follower attached, to suppress
            # asyncio's "exception was never retrieved" warning.  Followers
            # awaiting the future already retrieve it via `await existing`.
            if future.done():
                with contextlib.suppress(asyncio.CancelledError, asyncio.InvalidStateError):
                    future.exception()
            raise
        else:
            if not future.done():
                future.set_result(result)
            return result
        finally:
            # Always evict; next caller for this key starts a fresh flight.
            self._inflight.pop(key, None)

    def in_flight_keys(self) -> list[str]:
        """Return a snapshot of currently in-flight keys (for diagnostics)."""
        return list(self._inflight.keys())


__all__ = ["SingleFlightGroup"]

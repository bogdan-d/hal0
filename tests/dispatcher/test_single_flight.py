"""Unit tests for ``hal0.dispatcher.single_flight.SingleFlightGroup``.

Core invariant (PLAN.md §5 Tier 3): N concurrent calls with the same key
share exactly **one** underlying function invocation.  All waiters receive
the same value (or the same exception) without a retry storm.
"""

from __future__ import annotations

import asyncio

import pytest

from hal0.dispatcher.single_flight import SingleFlightGroup


@pytest.mark.asyncio
async def test_100_concurrent_identical_calls_share_one_invocation() -> None:
    """100 concurrent ``do(key, fn)`` calls → fn is invoked exactly once.

    This is the headline Tier 3 guarantee from PLAN.md §5: cold-cache
    prefetch fan-in collapses to a single upstream HTTP request.
    """
    group = SingleFlightGroup()
    invocations = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def fn() -> str:
        nonlocal invocations
        invocations += 1
        started.set()
        # Block until the test releases us — guarantees followers attach.
        await release.wait()
        return "shared-result"

    # Kick off 100 concurrent waiters.
    tasks = [asyncio.create_task(group.do("same-key", fn)) for _ in range(100)]

    await started.wait()
    # At this point, exactly one call has started; the rest are queued on
    # the shared future.  Confirm the in-flight key is visible.
    assert "same-key" in group.in_flight_keys()
    release.set()

    results = await asyncio.gather(*tasks)
    assert invocations == 1
    assert results == ["shared-result"] * 100
    # In-flight map cleaned up after completion.
    assert group.in_flight_keys() == []


@pytest.mark.asyncio
async def test_distinct_keys_run_independently() -> None:
    group = SingleFlightGroup()
    invocations: dict[str, int] = {}

    async def fn(key: str) -> str:
        invocations[key] = invocations.get(key, 0) + 1
        await asyncio.sleep(0)
        return f"result-{key}"

    a, b = await asyncio.gather(
        group.do("a", fn, "a"),
        group.do("b", fn, "b"),
    )
    assert a == "result-a"
    assert b == "result-b"
    assert invocations == {"a": 1, "b": 1}


@pytest.mark.asyncio
async def test_exception_is_shared_with_all_waiters() -> None:
    """On error, every waiter sees the same exception — no retry storm."""

    group = SingleFlightGroup()
    invocations = 0
    started = asyncio.Event()
    release = asyncio.Event()

    class Boom(RuntimeError):
        pass

    async def fn() -> str:
        nonlocal invocations
        invocations += 1
        started.set()
        await release.wait()
        raise Boom("upstream exploded")

    tasks = [asyncio.create_task(group.do("k", fn)) for _ in range(20)]
    await started.wait()
    release.set()

    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert invocations == 1
    assert all(isinstance(r, Boom) for r in results)
    # Same instance shared via the future.
    first_exc = results[0]
    assert all(r is first_exc for r in results)


@pytest.mark.asyncio
async def test_second_call_after_completion_runs_fresh() -> None:
    """In-flight map evicts after completion so a later call runs again."""

    group = SingleFlightGroup()
    invocations = 0

    async def fn() -> int:
        nonlocal invocations
        invocations += 1
        return invocations

    first = await group.do("k", fn)
    second = await group.do("k", fn)
    assert first == 1
    assert second == 2


@pytest.mark.asyncio
async def test_kwargs_and_args_pass_through() -> None:
    group = SingleFlightGroup()

    async def fn(a: int, b: int, *, c: int = 0) -> int:
        return a + b + c

    assert await group.do("k", fn, 1, 2, c=3) == 6

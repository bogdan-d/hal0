"""Unit tests for hal0.upstreams.registry.

Covers:
  - CRUD (add / get / remove / update / list / from_slot / in_priority_order)
  - Auth header dispatch by auth_style
  - TIER1: adaptive cold-boot backoff — step sequence, jitter, total grace cap,
    per-slot override from hardware.json
  - TIER2: negative-tps clamp + counter-reset warning

The async warmup path patches `asyncio.sleep` and `time.monotonic` so the test
suite finishes in milliseconds, not minutes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hal0.upstreams import registry as registry_mod
from hal0.upstreams.registry import (
    TIER1_BACKOFF_JITTER_FRAC,
    TIER1_BACKOFF_STEPS,
    TIER1_TOTAL_GRACE_S,
    Upstream,
    UpstreamAlreadyExists,
    UpstreamNotFound,
    UpstreamRegistry,
)


def _slot(name: str = "primary", port: int = 8081, **kw: Any) -> Upstream:
    defaults: dict[str, Any] = dict(
        name=name,
        kind="slot",
        url=f"http://127.0.0.1:{port}/v1",
        slot_name=name,
        warmup_strategy="ondemand",
        ttl_warmup_seconds=TIER1_TOTAL_GRACE_S,
    )
    defaults.update(kw)
    return Upstream(**defaults)


def _remote(name: str = "openrouter", **kw: Any) -> Upstream:
    defaults: dict[str, Any] = dict(
        name=name,
        kind="remote",
        url="https://openrouter.ai/api/v1",
        auth_value_env="OPENROUTER_API_KEY",
    )
    defaults.update(kw)
    return Upstream(**defaults)


# ── CRUD ──────────────────────────────────────────────────────────────────────


def test_add_and_get() -> None:
    r = UpstreamRegistry()
    u = _slot()
    r.add(u)
    assert r.get("primary") is u
    assert r.get("missing") is None


def test_add_duplicate_raises() -> None:
    r = UpstreamRegistry()
    r.add(_slot())
    with pytest.raises(UpstreamAlreadyExists):
        r.add(_slot())


def test_upsert_overwrites() -> None:
    r = UpstreamRegistry()
    r.add(_slot())
    r.upsert(_slot(port=8090))
    assert r.get("primary").url.endswith(":8090/v1")


def test_remove() -> None:
    r = UpstreamRegistry()
    r.add(_slot())
    assert r.remove("primary") is True
    assert r.remove("primary") is False
    assert r.get("primary") is None


def test_update_merges_fields() -> None:
    r = UpstreamRegistry()
    r.add(_slot())
    new = r.update("primary", warmup_strategy="always")
    assert new.warmup_strategy == "always"
    assert r.get("primary").warmup_strategy == "always"


def test_update_missing_raises() -> None:
    r = UpstreamRegistry()
    with pytest.raises(UpstreamNotFound):
        r.update("ghost", warmup_strategy="none")


def test_list_and_priority_order() -> None:
    r = UpstreamRegistry()
    r.add(_remote("openai"))
    r.add(_slot("primary"))
    r.add(_remote("anthropic"))
    names = [u.name for u in r.list()]
    assert set(names) == {"openai", "primary", "anthropic"}
    ordered = [u.name for u in r.in_priority_order()]
    # slots before remotes; remotes sorted by name
    assert ordered == ["primary", "anthropic", "openai"]


def test_from_slot() -> None:
    r = UpstreamRegistry()
    r.add(_slot("embed", port=8082))
    r.add(_remote())
    assert r.from_slot("embed").name == "embed"
    assert r.from_slot("nope") is None


# ── Auth headers ──────────────────────────────────────────────────────────────


def test_auth_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_KEY", "sk-abc")
    r = UpstreamRegistry()
    u = _remote(auth_style="bearer", auth_value_env="MY_KEY")
    headers = r.auth_headers(u)
    assert headers == {"Authorization": "Bearer sk-abc"}


def test_auth_bearer_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MY_KEY", raising=False)
    r = UpstreamRegistry()
    u = _remote(auth_style="bearer", auth_value_env="MY_KEY")
    assert r.auth_headers(u) == {}


def test_auth_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xyz")
    r = UpstreamRegistry()
    u = _remote(
        name="anthropic",
        url="https://api.anthropic.com/v1",
        auth_style="anthropic",
        auth_value_env="ANTHROPIC_API_KEY",
    )
    headers = r.auth_headers(u)
    assert headers["x-api-key"] == "sk-ant-xyz"
    assert headers["anthropic-version"] == "2023-06-01"


def test_auth_none() -> None:
    r = UpstreamRegistry()
    u = _remote(auth_style="none")
    assert r.auth_headers(u) == {}


def test_auth_google_query_emits_no_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("G_KEY", "foo")
    r = UpstreamRegistry()
    u = _remote(auth_style="google_query", auth_value_env="G_KEY")
    assert r.auth_headers(u) == {}


# ── TIER1: adaptive backoff ───────────────────────────────────────────────────


def test_tier1_constants_match_spec() -> None:
    """TIER1: probe intervals (0.5, 1, 2, 5, 10), grace 180s, jitter ±25%."""
    assert TIER1_BACKOFF_STEPS == (0.5, 1.0, 2.0, 5.0, 10.0)
    assert TIER1_BACKOFF_JITTER_FRAC == 0.25
    assert TIER1_TOTAL_GRACE_S == 180.0


@pytest.mark.asyncio
async def test_warmup_backoff_step_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    """The warmup loop sleeps for each step (0.5, 1, 2, 5, 10) ±25% in order."""
    r = UpstreamRegistry()
    u = _slot()
    r.add(u)

    # Always-unhealthy probe → warmup will exhaust the grace window.
    async def never_healthy(_: Upstream) -> bool:
        return False

    monkeypatch.setattr(r, "health", never_healthy)

    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)

    monkeypatch.setattr(registry_mod.asyncio, "sleep", fake_sleep)

    # Use a deterministic monotonic so the deadline truncates last sleeps.
    base = [0.0]

    def fake_monotonic() -> float:
        # Advance virtual clock by whatever we just slept.
        # First call sets the deadline; subsequent calls reflect accumulated sleep.
        if sleeps:
            base[0] = sum(sleeps)
        return base[0]

    monkeypatch.setattr(registry_mod.time, "monotonic", fake_monotonic)

    # Force jitter to 0 for the sequence assertion (we test jitter separately).
    monkeypatch.setattr(registry_mod.random, "uniform", lambda lo, hi: 0.0)

    ok = await r.warmup(u)
    assert ok is False

    # With no jitter, the recorded sleeps must be the exact step sequence
    # repeating the last value (10s) until 180s deadline.
    assert sleeps[:5] == [0.5, 1.0, 2.0, 5.0, 10.0]
    # After step 5 (cumulative 18.5s), the remaining cap-step sleeps are 10s
    # each until the deadline (180s). The final sleep may be truncated.
    rest = sleeps[5:]
    assert all(s <= 10.0 + 1e-9 for s in rest)
    assert pytest.approx(sum(sleeps), abs=1e-6) == 180.0


@pytest.mark.asyncio
async def test_warmup_backoff_jitter_within_25_percent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each sleep stays within ±25% of its nominal step (TIER1 jitter band)."""
    r = UpstreamRegistry()
    u = _slot()
    r.add(u)

    monkeypatch.setattr(r, "health", lambda _: _async_false())

    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)

    monkeypatch.setattr(registry_mod.asyncio, "sleep", fake_sleep)

    base = [0.0]

    def fake_monotonic() -> float:
        if sleeps:
            base[0] = sum(sleeps)
        return base[0]

    monkeypatch.setattr(registry_mod.time, "monotonic", fake_monotonic)

    await r.warmup(u)

    # First 5 sleeps map to the 5 nominal steps; assert each within band.
    for sleep, nominal in zip(sleeps[:5], TIER1_BACKOFF_STEPS, strict=False):
        assert sleep >= nominal * (1 - TIER1_BACKOFF_JITTER_FRAC) - 1e-9
        assert sleep <= nominal * (1 + TIER1_BACKOFF_JITTER_FRAC) + 1e-9


async def _async_false() -> bool:
    return False


async def _async_true() -> bool:
    return True


@pytest.mark.asyncio
async def test_warmup_total_grace_caps_at_180s(monkeypatch: pytest.MonkeyPatch) -> None:
    """No matter how many attempts, total cumulative sleep <= 180s."""
    r = UpstreamRegistry()
    u = _slot()
    r.add(u)

    monkeypatch.setattr(r, "health", lambda _: _async_false())

    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)

    monkeypatch.setattr(registry_mod.asyncio, "sleep", fake_sleep)

    base = [0.0]

    def fake_monotonic() -> float:
        if sleeps:
            base[0] = sum(sleeps)
        return base[0]

    monkeypatch.setattr(registry_mod.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(registry_mod.random, "uniform", lambda lo, hi: 0.0)

    ok = await r.warmup(u)
    assert ok is False
    assert sum(sleeps) <= TIER1_TOTAL_GRACE_S + 1e-9


@pytest.mark.asyncio
async def test_warmup_returns_true_when_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Warmup returns True as soon as health() succeeds (no needless sleeps after)."""
    r = UpstreamRegistry()
    u = _slot()
    r.add(u)

    healthy_after: dict[str, int] = {"count": 0}

    async def health(_: Upstream) -> bool:
        healthy_after["count"] += 1
        return healthy_after["count"] >= 3  # healthy on the 3rd probe

    monkeypatch.setattr(r, "health", health)

    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)

    monkeypatch.setattr(registry_mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(registry_mod.random, "uniform", lambda lo, hi: 0.0)

    ok = await r.warmup(u)
    assert ok is True
    # First probe is inside the lock (no sleep), then 2 backoff sleeps before
    # the third health probe returns True.
    assert len(sleeps) == 2
    assert sleeps == [0.5, 1.0]


@pytest.mark.asyncio
async def test_warmup_strategy_none_just_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    """warmup_strategy == 'none' delegates to a single health probe."""
    r = UpstreamRegistry()
    u = _slot(warmup_strategy="none")
    r.add(u)
    monkeypatch.setattr(r, "health", lambda _: _async_true())
    ok = await r.warmup(u)
    assert ok is True


@pytest.mark.asyncio
async def test_warmup_non_slot_returns_false() -> None:
    r = UpstreamRegistry()
    u = _remote()
    r.add(u)
    assert await r.warmup(u) is False


def test_load_slot_overrides_from_hardware_json(tmp_path: Path) -> None:
    """TIER1 per-slot override: backoff_steps + warmup_grace_s from hardware.json."""
    hw = tmp_path / "hardware.json"
    hw.write_text(
        json.dumps(
            {
                "slots": {
                    "primary": {
                        "backoff_steps": [0.1, 0.2, 0.4],
                        "warmup_grace_s": 30,
                    }
                }
            }
        )
    )
    r = UpstreamRegistry()
    r.load_slot_overrides(hw)
    u = _slot()
    assert r._effective_backoff_steps(u) == (0.1, 0.2, 0.4)
    assert r._effective_total_grace_s(u) == 30.0


def test_load_slot_overrides_missing_file(tmp_path: Path) -> None:
    r = UpstreamRegistry()
    r.load_slot_overrides(tmp_path / "nope.json")
    u = _slot()
    assert r._effective_backoff_steps(u) == TIER1_BACKOFF_STEPS
    assert r._effective_total_grace_s(u) == TIER1_TOTAL_GRACE_S


def test_load_slot_overrides_malformed(tmp_path: Path) -> None:
    hw = tmp_path / "hardware.json"
    hw.write_text("not json at all {{{")
    r = UpstreamRegistry()
    r.load_slot_overrides(hw)
    u = _slot()
    # Falls back to the defaults baked into the Upstream.
    assert r._effective_backoff_steps(u) == TIER1_BACKOFF_STEPS


@pytest.mark.asyncio
async def test_warmup_uses_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Per-slot override actually drives the sleep sequence."""
    hw = tmp_path / "hardware.json"
    hw.write_text(
        json.dumps(
            {
                "slots": {
                    "primary": {
                        "backoff_steps": [0.1, 0.1],
                        "warmup_grace_s": 0.5,
                    }
                }
            }
        )
    )
    r = UpstreamRegistry()
    r.load_slot_overrides(hw)
    u = _slot()
    r.add(u)

    monkeypatch.setattr(r, "health", lambda _: _async_false())

    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)

    monkeypatch.setattr(registry_mod.asyncio, "sleep", fake_sleep)

    base = [0.0]

    def fake_monotonic() -> float:
        if sleeps:
            base[0] = sum(sleeps)
        return base[0]

    monkeypatch.setattr(registry_mod.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(registry_mod.random, "uniform", lambda lo, hi: 0.0)

    ok = await r.warmup(u)
    assert ok is False
    assert sum(sleeps) <= 0.5 + 1e-9
    # Each sleep must be one of the override step values (after jitter=0).
    for s in sleeps:
        assert s <= 0.1 + 1e-9


# ── TIER2: negative tps clamp ─────────────────────────────────────────────────


def test_tps_first_sample_returns_zero() -> None:
    r = UpstreamRegistry()
    tps = r.record_tokens("primary", token_counter=100, now=1.0)
    assert tps == 0.0


def test_tps_normal_progression() -> None:
    r = UpstreamRegistry()
    r.record_tokens("primary", token_counter=0, now=0.0)
    tps = r.record_tokens("primary", token_counter=50, now=5.0)
    assert tps == pytest.approx(10.0)
    assert r.get_tps("primary") == pytest.approx(10.0)


def test_tps_clamps_negative_to_zero(caplog: pytest.LogCaptureFixture) -> None:
    """TIER2: counter reset (process restart) must not produce negative tps."""
    r = UpstreamRegistry()
    r.record_tokens("primary", token_counter=10_000, now=10.0)
    tps = r.record_tokens("primary", token_counter=42, now=15.0)
    assert tps == 0.0
    assert r.get_tps("primary") == 0.0


def test_tps_logs_warning_on_counter_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """TIER2: a warning is emitted when the counter goes backwards."""
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeLog:
        def info(self, *a: Any, **kw: Any) -> None: ...
        def debug(self, *a: Any, **kw: Any) -> None: ...
        def warning(self, event: str, **kw: Any) -> None:
            calls.append((event, kw))

    monkeypatch.setattr(registry_mod, "log", FakeLog())
    r = UpstreamRegistry()
    r.record_tokens("primary", token_counter=10_000, now=10.0)
    r.record_tokens("primary", token_counter=42, now=15.0)
    assert any(evt == "upstream.tps_counter_reset" for evt, _ in calls)


def test_tps_zero_delta_t_keeps_value_non_negative() -> None:
    r = UpstreamRegistry()
    r.record_tokens("primary", token_counter=100, now=1.0)
    tps = r.record_tokens("primary", token_counter=200, now=1.0)
    # Same instant — tps holds at the previous (clamped) value, which was 0.
    assert tps >= 0.0

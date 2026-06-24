"""Unit + golden-parity tests for hal0.slots.argv.normalize_argv.

The golden fixture is the *live* ``agent`` slot's resolved command (captured
from ``slot_list`` on CT105), which carries the real duplicate-flag soup
(``-b`` x2, ``-ctk`` x2, ``--jinja`` x2, ``--threads`` long + ``-t`` short).
The parity property: normalising it preserves every flag's effective (last)
value and drops only the earlier duplicates — so the slot launches identically.
"""

from __future__ import annotations

from hal0.slots.argv import normalize_argv, resolve_argv

# The flag portion of the live `agent` slot resolved_command (post `--port`).
# Verbatim from `mcp__hal0-admin__slot_list` — includes the profile MTP bundle
# AND the slot extra_args repeating many of the same flags.
AGENT_LIVE = [
    "--host",
    "0.0.0.0",
    "--port",
    "8101",
    "--model",
    "qwen3.6-35b-a3b-crown-halo-mtp-dynamic",
    "--alias",
    "qwen3.6-35b-a3b-crown-halo-mtp-dynamic",
    "--ctx-size",
    "164000",
    "-fa",
    "on",
    "-ctk",
    "q4_0",
    "-ctv",
    "q4_0",
    "-b",
    "8192",
    "-ub",
    "2048",
    "--parallel",
    "1",
    "--threads",
    "16",
    "--threads-batch",
    "32",
    "--no-mmap",
    "--poll",
    "100",
    "--poll-batch",
    "1",
    "--jinja",
    "--spec-type",
    "draft-mtp",
    "--spec-draft-device",
    "ROCm0",
    "--spec-draft-ngl",
    "all",
    "--spec-draft-n-max",
    "4",
    "--spec-draft-n-min",
    "0",
    "--spec-draft-p-min",
    "0.0",
    "--spec-draft-p-split",
    "0.10",
    "--spec-draft-type-k",
    "f16",
    "--spec-draft-type-v",
    "f16",
    "--spec-draft-threads",
    "16",
    "--spec-draft-threads-batch",
    "32",
    "--spec-draft-poll",
    "1",
    "--spec-draft-poll-batch",
    "1",
    # ── slot [server].extra_args begins here — repeats much of the above ──
    "-ngl",
    "999",
    "-dev",
    "ROCm0",
    "-sm",
    "row",
    "-b",
    "8192",
    "-ub",
    "2048",
    "-t",
    "16",
    "-tb",
    "32",
    "-ctk",
    "q4_0",
    "-ctv",
    "q4_0",
    "--spec-draft-device",
    "ROCm0",
    "--spec-draft-ngl",
    "all",
    "--spec-draft-type-k",
    "f16",
    "--spec-draft-type-v",
    "f16",
    "--spec-draft-threads",
    "16",
    "--spec-draft-threads-batch",
    "32",
    "--spec-draft-n-max",
    "4",
    "--spec-draft-n-min",
    "0",
    "--spec-draft-p-min",
    "0.0",
    "--spec-draft-p-split",
    "0.10",
    "--poll",
    "100",
    "--poll-batch",
    "1",
    "--spec-draft-poll",
    "1",
    "--spec-draft-poll-batch",
    "1",
    "--temp",
    "0",
    "--min-p",
    "0.0",
    "--top-p",
    "0.9",
    "--top-k",
    "20",
    "--repeat-penalty",
    "1.0",
    "--seed",
    "123",
    "--cache-ram",
    "0",
    "--parallel",
    "1",
    "--image-min-tokens",
    "1024",
    "--metrics",
    "--jinja",
    "--reasoning-format",
    "deepseek",
    "--reasoning-budget",
    "0",
]


def _value_after(tokens: list[str], flag: str) -> str | None:
    """Last value following ``flag`` in ``tokens`` (the effective value)."""
    val = None
    for i, t in enumerate(tokens):
        if t == flag and i + 1 < len(tokens):
            val = tokens[i + 1]
    return val


# ── golden parity on the live agent slot ──────────────────────────────────────


def test_agent_live_dedups_but_preserves_effective_values() -> None:
    res = normalize_argv(AGENT_LIVE)
    out = res.argv

    # 1) duplicates were actually removed
    assert res.removed > 0
    assert len(out) < len(AGENT_LIVE)

    # 2) each dedupable flag now appears exactly once
    for flag in ("-b", "-ub", "-ctk", "-ctv", "--jinja", "--parallel", "--poll"):
        assert out.count(flag) <= 1, f"{flag} still duplicated: {out.count(flag)}"

    # 3) effective (last) value preserved for representative scalar flags
    assert _value_after(out, "-b") == "8192"
    assert _value_after(out, "-ctk") == "q4_0"
    assert _value_after(out, "--spec-draft-type-k") == "f16"
    assert _value_after(out, "--reasoning-budget") == "0"
    assert _value_after(out, "--temp") == "0"

    # 4) structural prefix intact
    assert out[:4] == ["--host", "0.0.0.0", "--port", "8101"]
    assert _value_after(out, "--model") == "qwen3.6-35b-a3b-crown-halo-mtp-dynamic"
    assert _value_after(out, "--ctx-size") == "164000"

    # 5) bool flag survives exactly once
    assert out.count("--jinja") == 1
    assert out.count("--metrics") == 1


def test_alias_dedups_short_against_long() -> None:
    # --threads (long, from profile) and -t (short, from extra_args) share a key.
    res = normalize_argv(["--threads", "16", "-t", "16"])
    assert res.argv == ["-t", "16"]  # last occurrence wins, short spelling kept
    assert res.removed == 1


def test_normalize_is_idempotent() -> None:
    once = normalize_argv(AGENT_LIVE).argv
    twice = normalize_argv(once)
    assert twice.argv == once
    assert twice.removed == 0


# ── focused unit cases ────────────────────────────────────────────────────────


def test_last_value_wins_on_conflict() -> None:
    res = normalize_argv(["-b", "512", "-b", "8192"])
    assert res.argv == ["-b", "8192"]
    assert res.removed == 1


def test_bool_flags_collapse_to_one() -> None:
    res = normalize_argv(["--jinja", "--metrics", "--jinja"])
    assert res.argv == ["--metrics", "--jinja"]  # --jinja kept at its last spot
    assert res.removed == 1


def test_append_flags_are_never_deduped() -> None:
    res = normalize_argv(["--lora", "a.gguf", "--lora", "b.gguf"])
    assert res.argv == ["--lora", "a.gguf", "--lora", "b.gguf"]
    assert res.removed == 0


def test_negative_number_is_a_value_not_a_flag() -> None:
    res = normalize_argv(["-ngl", "-1"])
    assert res.argv == ["-ngl", "-1"]
    assert _value_after(res.argv, "-ngl") == "-1"


def test_bare_positionals_preserved() -> None:
    res = normalize_argv(["--model", "/m.gguf", "extra-positional"])
    assert "extra-positional" in res.argv


def test_empty_is_noop() -> None:
    res = normalize_argv([])
    assert res.argv == []
    assert res.removed == 0
    assert res.winners == {}


# ── resolve_argv: provenance over labelled segments ───────────────────────────


def test_resolve_argv_attributes_winning_source() -> None:
    res = resolve_argv(
        [
            ("base", ["--host", "0.0.0.0"]),
            ("profile", ["-b", "512", "--jinja"]),
            ("extra_args", ["-b", "8192"]),  # overrides the profile's -b
        ]
    )
    assert res.argv == ["--host", "0.0.0.0", "--jinja", "-b", "8192"]
    prov = {p.flag: p for p in res.provenance}
    # -b was set last by extra_args -> that segment is credited, value preserved
    assert prov["-b"].source == "extra_args"
    assert prov["-b"].value == "8192"
    # --jinja only came from the profile
    assert prov["--jinja"].source == "profile"
    assert prov["--jinja"].value is None
    # --host from base
    assert prov["--host"].source == "base"
    assert res.removed == 1


def test_resolve_argv_equivalent_argv_to_normalize() -> None:
    # Same tokens, segmented vs flat, produce the same deduped argv.
    flat = ["--host", "0.0.0.0", "-b", "512", "--jinja", "-b", "8192"]
    seg = resolve_argv([("base", flat[:2]), ("profile", flat[2:5]), ("extra_args", flat[5:])])
    assert seg.argv == normalize_argv(flat).argv


def test_resolve_argv_omits_append_flags_from_provenance() -> None:
    res = resolve_argv([("profile", ["--lora", "a", "--lora", "b"]), ("extra_args", ["--jinja"])])
    flags = {p.flag for p in res.provenance}
    assert "--lora" not in flags  # append flags aren't deduped -> no single "winner"
    assert "--jinja" in flags

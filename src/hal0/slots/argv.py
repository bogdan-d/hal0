"""normalize_argv — the single dedup/last-wins pass for llama-server argv.

The launch argv for a slot is assembled from several sources that historically
just concatenate (``container._llama_launch_plan``): the structural prefix
(``--host``/``--port``/``--model``/``--alias``/``--ctx-size``), the profile's
bench-tuned ``flags``, a resolved ``--chat-template-file``, and the slot's
``[server].extra_args``. Nothing dedups *across* those segments, so a flag the
profile sets and the slot also overrides (``-b``, ``-ctk``, ``-ngl``,
``--jinja`` …) is emitted twice. llama-server silently takes the **last**
occurrence, so the command still runs — but the rendered argv is a confusing,
unauditable soup of conflicting duplicates (the live ``agent`` slot ships
``-b`` x2, ``-ngl 999`` then ``-ngl 99``, ``--jinja`` x2).

This module collapses that to one source of truth at the argv layer:

  * **Dedup by canonical key, keep the LAST occurrence.** Because llama-server
    already used the last value, keeping it is *effective-value-preserving* —
    the slot launches identically, the argv is just clean. This is the property
    the golden-parity tests pin.
  * **Canonicalize for the key only; emit the original spelling.** ``-b`` and
    ``--batch-size`` share a key (so they dedup against each other), but the
    surviving token keeps whatever spelling the winning source used — we never
    rewrite ``-b`` into ``--batch-size`` behind the operator's back.
  * **Append-list flags are never deduped** (``--lora``/``--draft-model``/
    ``--override-kv``): llama-server treats repeats additively.
  * **Order is preserved** (each surviving flag stays at its last position),
    so the structural prefix stays first and the diff vs today is exactly "the
    earlier duplicates removed".

It is a pure function over a token list, so every assembly path
(``_llama_launch_plan``, the resolved-command preview) can route through it
without restructuring how they build the list.
"""

from __future__ import annotations

from dataclasses import dataclass

# Short→long canonicalisation. Used ONLY to compute the dedup key; the emitted
# token keeps its original spelling. Seeded from the flags hal0 profiles +
# slots actually use on llama-server; unknown flags fall through unaliased and
# dedup against their own literal spelling (still correct, just less aggressive).
FLAG_ALIASES: dict[str, str] = {
    "-b": "--batch-size",
    "-ub": "--ubatch-size",
    "-ngl": "--n-gpu-layers",
    "-ctk": "--cache-type-k",
    "-ctv": "--cache-type-v",
    "-t": "--threads",
    "-tb": "--threads-batch",
    "-fa": "--flash-attn",
    "-dev": "--device",
    "-sm": "--split-mode",
    "-c": "--ctx-size",
    "-ts": "--tensor-split",
    "-mg": "--main-gpu",
    "-np": "--parallel",
    "-ngld": "--n-gpu-layers-draft",
}

# Flags whose semantics are "may be repeated" — never deduped. Keyed by the
# canonical (long) spelling.
APPEND_FLAGS: frozenset[str] = frozenset(
    {
        "--lora",
        "--draft-model",
        "--override-kv",
    }
)


@dataclass(frozen=True)
class NormalizedArgv:
    """Result of :func:`normalize_argv`.

    ``argv`` is the deduped token list. ``removed`` is the count of duplicate
    tokens dropped (for logging / the dashboard "cleaned N duplicate flags"
    affordance). ``winners`` maps each canonical flag key to the spelling that
    survived — the seed of a future provenance view.
    """

    argv: list[str]
    removed: int
    winners: dict[str, str]


def _is_flag(tok: str) -> bool:
    """True for ``--long`` and ``-x``/``-ngl`` short flags; False for values.

    A leading ``-`` followed by a letter is a flag; a leading ``-`` followed by
    a digit/dot is a negative number (a value, e.g. ``-1`` for ``-ngl -1``).
    """
    if tok.startswith("--"):
        return len(tok) > 2
    return len(tok) > 1 and tok[0] == "-" and tok[1].isalpha()


def _canon(flag: str) -> str:
    return FLAG_ALIASES.get(flag, flag)


@dataclass(frozen=True)
class _Pair:
    canon: str | None  # None => bare positional (never deduped)
    flag: str | None
    values: tuple[str, ...]


def _split_pairs(tokens: list[str]) -> list[_Pair]:
    """Group a flat token list into ``(flag, value?)`` pairs, order preserved.

    A flag consumes the following token as its value iff that token is not
    itself a flag (so ``--jinja --metrics`` are two valueless bools, while
    ``-b 8192`` and ``--temp 0`` carry a value). Bare positionals are kept
    under ``canon=None`` so dedup never touches them.
    """
    pairs: list[_Pair] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if _is_flag(tok):
            if i + 1 < n and not _is_flag(tokens[i + 1]):
                pairs.append(_Pair(_canon(tok), tok, (tokens[i + 1],)))
                i += 2
            else:
                pairs.append(_Pair(_canon(tok), tok, ()))
                i += 1
        else:
            pairs.append(_Pair(None, None, (tok,)))
            i += 1
    return pairs


def normalize_argv(tokens: list[str]) -> NormalizedArgv:
    """Dedup ``tokens`` keeping the last occurrence of each scalar/bool flag.

    Effective-value-preserving: the surviving value for every flag equals the
    last value in ``tokens`` (what llama-server used anyway). Append-list flags
    and bare positionals are kept verbatim, in order.
    """
    pairs = _split_pairs(tokens)

    # The index of the last occurrence of each dedupable canonical flag.
    last_index: dict[str, int] = {}
    for idx, p in enumerate(pairs):
        if p.canon is not None and p.canon not in APPEND_FLAGS:
            last_index[p.canon] = idx

    out: list[str] = []
    winners: dict[str, str] = {}
    removed = 0
    for idx, p in enumerate(pairs):
        if p.canon is None:  # positional
            out.extend(p.values)
            continue
        if p.canon in APPEND_FLAGS:
            assert p.flag is not None
            out.append(p.flag)
            out.extend(p.values)
            continue
        if last_index[p.canon] == idx:
            assert p.flag is not None
            out.append(p.flag)
            out.extend(p.values)
            winners[p.canon] = p.flag
        else:
            removed += 1  # earlier duplicate, dropped in favour of a later one

    return NormalizedArgv(argv=out, removed=removed, winners=winners)


__all__ = ["APPEND_FLAGS", "FLAG_ALIASES", "NormalizedArgv", "normalize_argv"]

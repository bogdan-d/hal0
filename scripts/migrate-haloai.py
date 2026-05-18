#!/usr/bin/env python3
"""haloai → hal0 model migration (PLAN §11 step 2).

Reads a curated allow-list of model directories from the shared
HuggingFace cache (default ``/mnt/ai-models/huggingface/hub``) and
writes a hal0 ``registry.toml`` describing the resolved entries.

**Scope (v1):** models only. No slot configs, no providers.toml, no
upstreams.toml, no openwebui state — operator runs the FirstRun wizard
fresh post-cutover to bind models to slots.

Models stay on the shared NFS mount. The output is just a registry
file the operator drops into ``/var/lib/hal0/registry/registry.toml``.

Usage (on the haloai LXC):
    python3 scripts/migrate-haloai.py \\
        --hub-root /mnt/ai-models/huggingface/hub \\
        --output   /tmp/hal0-migration-out \\
        --dry-run

Then rsync ``/tmp/hal0-migration-out/var/lib/hal0/registry/`` into
``/var/lib/hal0/registry/`` after running ``install.sh``.
"""

from __future__ import annotations

import argparse
import dataclasses
import shutil
import sys
import tomllib
from pathlib import Path

import structlog
import tomli_w

# Allow `from hal0.registry.model import Model` when run from a hal0 checkout.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if (_REPO_ROOT / "src" / "hal0").is_dir():
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from hal0.registry.model import Model  # noqa: E402
from hal0.registry.store import model_to_toml_dict  # noqa: E402

log = structlog.get_logger(__name__)


# ── Errors ─────────────────────────────────────────────────────────────────────


class MigrationError(Exception):
    """Migration script failed in a way the operator must act on."""


# ── Allow-list entry ───────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class AllowEntry:
    """One row in the curated allow-list.

    ``hf_pattern`` is a glob applied inside ``snapshots/<sha>/``; the
    resolver picks the LARGEST matching file (typically the highest quant).
    Use ``"*"`` when the repo isn't a GGUF cache (AWQ, MXFP4, raw weights).
    """

    id: str
    name: str
    capabilities: tuple[str, ...]
    license: str
    hf_repo: str
    hf_pattern: str = "*.gguf"


DEFAULT_ALLOWLIST: tuple[AllowEntry, ...] = (
    AllowEntry(
        id="qwen3-coder-next",
        name="Qwen3 Coder Next (GGUF)",
        capabilities=("code", "chat"),
        license="Apache-2.0",
        hf_repo="unsloth/Qwen3-Coder-Next-GGUF",
        hf_pattern="*.gguf",
    ),
    AllowEntry(
        id="qwen3-coder-next-mxfp4",
        name="Qwen3 Coder Next (AMD MXFP4)",
        capabilities=("code", "chat", "npu"),
        license="Apache-2.0",
        hf_repo="amd/Qwen3-Coder-Next-MXFP4",
        hf_pattern="*",
    ),
    AllowEntry(
        id="qwen3.6-27b",
        name="Qwen3.6 27B (GGUF)",
        capabilities=("chat",),
        license="Apache-2.0",
        hf_repo="unsloth/Qwen3.6-27B-GGUF",
        hf_pattern="*.gguf",
    ),
    AllowEntry(
        id="qwen3.6-35b-a3b",
        name="Qwen3.6 35B A3B (GGUF)",
        capabilities=("chat",),
        license="Apache-2.0",
        hf_repo="unsloth/Qwen3.6-35B-A3B-GGUF",
        hf_pattern="*.gguf",
    ),
    AllowEntry(
        id="qwen3.6-27b-heretic-neo-code",
        name="Qwen3.6 27B Heretic NEO-CODE (DavidAU)",
        capabilities=("code", "chat", "uncensored"),
        license="Apache-2.0",
        hf_repo="DavidAU/Qwen3.6-27B-Heretic-Uncensored-FINETUNE-NEO-CODE-Di-IMatrix-MAX-GGUF",
        hf_pattern="*.gguf",
    ),
    AllowEntry(
        id="qwen3-coder-reap-25b",
        name="Qwen3 Coder REAP 25B A3B (cerebras/bartowski)",
        capabilities=("code", "chat"),
        license="Apache-2.0",
        hf_repo="bartowski/cerebras_Qwen3-Coder-REAP-25B-A3B-GGUF",
        hf_pattern="*.gguf",
    ),
    AllowEntry(
        id="qwen3-zero-coder-reasoning-0.8b-neo",
        name="Qwen3 Zero Coder Reasoning V2 0.8B NEO (DavidAU)",
        capabilities=("code", "tiny"),
        license="Apache-2.0",
        hf_repo="DavidAU/Qwen3-Zero-Coder-Reasoning-V2-0.8B-NEO-EX-GGUF",
        hf_pattern="*.gguf",
    ),
    AllowEntry(
        id="qwen3-next-80b-thinking",
        name="Qwen3-Next 80B A3B Thinking (AWQ 4bit)",
        capabilities=("chat", "reasoning"),
        license="Apache-2.0",
        hf_repo="cpatonn/Qwen3-Next-80B-A3B-Thinking-AWQ-4bit",
        hf_pattern="*",
    ),
    AllowEntry(
        id="qwen3.5-0.8b",
        name="Qwen3.5 0.8B (GGUF)",
        capabilities=("chat", "tiny"),
        license="Apache-2.0",
        hf_repo="unsloth/Qwen3.5-0.8B-GGUF",
        hf_pattern="*.gguf",
    ),
    AllowEntry(
        id="qwen3.5-4b",
        name="Qwen3.5 4B (GGUF)",
        capabilities=("chat",),
        license="Apache-2.0",
        hf_repo="unsloth/Qwen3.5-4B-GGUF",
        hf_pattern="*.gguf",
    ),
    AllowEntry(
        id="qwen3.5-9b",
        name="Qwen3.5 9B (GGUF)",
        capabilities=("chat",),
        license="Apache-2.0",
        hf_repo="unsloth/Qwen3.5-9B-GGUF",
        hf_pattern="*.gguf",
    ),
    AllowEntry(
        id="qwen3.5-35b-a3b",
        name="Qwen3.5 35B A3B (raw weights)",
        capabilities=("chat", "raw"),
        license="Apache-2.0",
        hf_repo="unsloth/Qwen3.5-35B-A3B",
        hf_pattern="*",
    ),
    AllowEntry(
        id="kappa-20b-mxfp4",
        name="kappa 20B 131k (eousphoros, MXFP4)",
        capabilities=("chat", "npu"),
        license="Apache-2.0",
        hf_repo="eousphoros/kappa-20b-131k-mxfp4",
        hf_pattern="*",
    ),
    AllowEntry(
        id="kappa-20b-i1-gguf",
        name="kappa 20B 131k (mradermacher, i1 GGUF)",
        capabilities=("chat",),
        license="Apache-2.0",
        hf_repo="mradermacher/kappa-20b-131k-i1-GGUF",
        hf_pattern="*.gguf",
    ),
)


# ── Resolve allow-list entries against the HF cache ───────────────────────────


def _hub_dirname(hf_repo: str) -> str:
    """Convert ``org/repo`` → HF cache dirname ``models--org--repo``."""
    return "models--" + hf_repo.replace("/", "--")


def _pick_largest(paths: list[Path]) -> Path | None:
    """Return the largest file from a list, or None if list is empty."""
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_size if p.is_file() else 0)


def resolve_entry(entry: AllowEntry, hub_root: Path) -> Path | None:
    """Resolve an allow-list entry to a file on disk, or None if absent.

    HF cache layout: ``<hub_root>/models--<org>--<repo>/snapshots/<sha>/``.
    Picks the largest file matching ``entry.hf_pattern`` across all
    snapshots. Snapshots whose files are broken symlinks are skipped.
    """
    repo_dir = hub_root / _hub_dirname(entry.hf_repo)
    if not repo_dir.is_dir():
        return None

    snapshots_dir = repo_dir / "snapshots"
    candidates: list[Path] = []
    if snapshots_dir.is_dir():
        for snapshot in snapshots_dir.iterdir():
            if not snapshot.is_dir():
                continue
            for match in snapshot.glob(entry.hf_pattern):
                # Resolve symlinks; only keep files that actually exist.
                try:
                    if match.is_file():
                        candidates.append(match)
                except OSError:
                    continue

    return _pick_largest(candidates)


def build_model(entry: AllowEntry, resolved: Path) -> Model:
    """Construct a validated ``Model`` from an allow-list entry + resolved path."""
    try:
        size = resolved.stat().st_size
    except OSError:
        size = 0
    return Model(
        id=entry.id,
        name=entry.name,
        path=str(resolved),
        size_bytes=size,
        license=entry.license,
        capabilities=list(entry.capabilities),
        hf_repo=entry.hf_repo,
        hf_filename=resolved.name,
        tags=["migrated", "curated"],
    )


# ── Allow-list loading (operator override) ────────────────────────────────────


def load_allowlist(path: Path | None) -> tuple[AllowEntry, ...]:
    """Load an allow-list from a TOML file, or return DEFAULT_ALLOWLIST."""
    if path is None:
        return DEFAULT_ALLOWLIST
    if not path.is_file():
        raise MigrationError(f"allowlist file not found: {path}")
    with path.open("rb") as f:
        data = tomllib.load(f)
    entries = data.get("models", [])
    if not isinstance(entries, list):
        raise MigrationError("allowlist must contain a [[models]] array")
    out: list[AllowEntry] = []
    for raw in entries:
        out.append(
            AllowEntry(
                id=raw["id"],
                name=raw.get("name", raw["id"]),
                capabilities=tuple(raw.get("capabilities", [])),
                license=raw.get("license", "unknown"),
                hf_repo=raw["hf_repo"],
                hf_pattern=raw.get("hf_pattern", "*.gguf"),
            )
        )
    return tuple(out)


# ── Registry serialisation ─────────────────────────────────────────────────────


def render_registry(models: list[Model]) -> bytes:
    """Render Model list as ``registry.toml`` bytes — matches ModelRegistry._atomic_write."""
    payload = {
        "models": {
            m.id: {k: v for k, v in model_to_toml_dict(m).items() if k != "id"}
            for m in sorted(models, key=lambda m: m.id)
        }
    }
    return tomli_w.dumps(payload).encode("utf-8")


# ── Main migration ─────────────────────────────────────────────────────────────


@dataclasses.dataclass
class MigrationSummary:
    resolved: list[str]
    skipped: list[str]
    output_path: Path | None  # None when dry-run


def _ensure_empty_or_force(path: Path, *, force: bool) -> None:
    if path.exists() and any(path.iterdir()) and not force:
        raise MigrationError(f"output dir {path} is not empty; pass --force to overwrite")


def migrate(
    *,
    hub_root: Path,
    output: Path,
    allowlist: tuple[AllowEntry, ...],
    dry_run: bool,
    force: bool,
) -> MigrationSummary:
    if not hub_root.is_dir():
        raise MigrationError(f"hub root not found: {hub_root}")

    resolved_models: list[Model] = []
    resolved_ids: list[str] = []
    skipped_ids: list[str] = []

    for entry in allowlist:
        resolved = resolve_entry(entry, hub_root)
        if resolved is None:
            log.warning("model.skip", id=entry.id, hf_repo=entry.hf_repo, reason="not_on_disk")
            skipped_ids.append(entry.id)
            continue
        model = build_model(entry, resolved)
        resolved_models.append(model)
        resolved_ids.append(entry.id)
        log.info(
            "model.resolved",
            id=entry.id,
            path=str(resolved),
            size_bytes=model.size_bytes,
        )

    if dry_run:
        log.info(
            "migrate.dry_run",
            resolved=len(resolved_ids),
            skipped=len(skipped_ids),
        )
        return MigrationSummary(
            resolved=resolved_ids,
            skipped=skipped_ids,
            output_path=None,
        )

    registry_dir = output / "var" / "lib" / "hal0" / "registry"
    _ensure_empty_or_force(output, force=force)
    if force and output.exists():
        shutil.rmtree(output)
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry_file = registry_dir / "registry.toml"
    registry_file.write_bytes(render_registry(resolved_models))
    log.info(
        "migrate.wrote_registry",
        path=str(registry_file),
        resolved=len(resolved_ids),
        skipped=len(skipped_ids),
    )
    return MigrationSummary(
        resolved=resolved_ids,
        skipped=skipped_ids,
        output_path=registry_file,
    )


# ── CLI ────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="migrate-haloai",
        description=(
            "haloai → hal0 model migration. Reads a curated allow-list "
            "from the shared HuggingFace cache, writes a hal0 registry.toml."
        ),
    )
    p.add_argument(
        "--hub-root",
        type=Path,
        default=Path("/mnt/ai-models/huggingface/hub"),
        help="HF cache root (default: /mnt/ai-models/huggingface/hub).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/hal0-migration-out"),
        help="Staging dir to write under (default: /tmp/hal0-migration-out).",
    )
    p.add_argument(
        "--allowlist",
        type=Path,
        default=None,
        help="Override allow-list TOML file. Default: 14-entry curated list.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve + validate, don't write anything.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Wipe existing --output dir before writing.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        allowlist = load_allowlist(args.allowlist)
        summary = migrate(
            hub_root=args.hub_root,
            output=args.output,
            allowlist=allowlist,
            dry_run=args.dry_run,
            force=args.force,
        )
    except MigrationError as exc:
        log.error("migrate.failed", reason=str(exc))
        return 2
    print(
        f"\nMigration {'(dry-run) ' if args.dry_run else ''}complete:"
        f"\n  resolved: {len(summary.resolved)}"
        f"\n  skipped:  {len(summary.skipped)}"
        + (f"\n  output:   {summary.output_path}" if summary.output_path else "")
        + (f"\n  skipped ids: {', '.join(summary.skipped)}" if summary.skipped else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

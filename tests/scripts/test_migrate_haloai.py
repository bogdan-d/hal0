"""Tests for scripts/migrate-haloai.py.

Hermetic — builds a synthetic HF cache layout under tmp_path, never touches
the real /mnt/ai-models. Every emitted Model is re-validated through the
hal0 pydantic schema so the registry file we write is well-formed by
construction.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

import pytest

from hal0.registry.model import Model

# Load scripts/migrate-haloai.py by path (hyphen in filename → can't import).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATE_PATH = _REPO_ROOT / "scripts" / "migrate-haloai.py"
_spec = importlib.util.spec_from_file_location("migrate_haloai", _MIGRATE_PATH)
assert _spec is not None and _spec.loader is not None
migrate_haloai = importlib.util.module_from_spec(_spec)
sys.modules["migrate_haloai"] = migrate_haloai
_spec.loader.exec_module(migrate_haloai)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_snapshot(hub: Path, hf_repo: str, sha: str, files: dict[str, int]) -> Path:
    """Build a snapshot dir with files of given byte sizes; returns the snapshot path."""
    dirname = "models--" + hf_repo.replace("/", "--")
    snap = hub / dirname / "snapshots" / sha
    snap.mkdir(parents=True, exist_ok=True)
    for fname, size in files.items():
        (snap / fname).write_bytes(b"\0" * size)
    return snap


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    """Return an empty HF cache hub root."""
    h = tmp_path / "hf-hub"
    h.mkdir()
    return h


# ── _hub_dirname ──────────────────────────────────────────────────────────────


def test_hub_dirname_translates_slash_to_dashdash() -> None:
    assert (
        migrate_haloai._hub_dirname("unsloth/Qwen3.5-4B-GGUF") == "models--unsloth--Qwen3.5-4B-GGUF"
    )


# ── resolve_entry ─────────────────────────────────────────────────────────────


def test_resolve_picks_largest_gguf(hub: Path) -> None:
    _make_snapshot(
        hub,
        "unsloth/Qwen3.5-4B-GGUF",
        sha="abc",
        files={"small.gguf": 100, "big.gguf": 9999, "README.md": 50},
    )
    entry = migrate_haloai.AllowEntry(
        id="qwen3.5-4b",
        name="Qwen3.5 4B",
        capabilities=("chat",),
        license="Apache-2.0",
        hf_repo="unsloth/Qwen3.5-4B-GGUF",
        hf_pattern="*.gguf",
    )
    resolved = migrate_haloai.resolve_entry(entry, hub)
    assert resolved is not None
    assert resolved.name == "big.gguf"


def test_resolve_returns_none_when_repo_missing(hub: Path) -> None:
    entry = migrate_haloai.AllowEntry(
        id="missing",
        name="missing",
        capabilities=("chat",),
        license="Apache-2.0",
        hf_repo="some/missing-repo",
    )
    assert migrate_haloai.resolve_entry(entry, hub) is None


def test_resolve_glob_star_matches_anything(hub: Path) -> None:
    _make_snapshot(
        hub,
        "amd/Qwen3-Coder-Next-MXFP4",
        sha="def",
        files={"model.safetensors": 5000, "config.json": 200},
    )
    entry = migrate_haloai.AllowEntry(
        id="qwen3-coder-next-mxfp4",
        name="...",
        capabilities=("code",),
        license="Apache-2.0",
        hf_repo="amd/Qwen3-Coder-Next-MXFP4",
        hf_pattern="*",
    )
    resolved = migrate_haloai.resolve_entry(entry, hub)
    assert resolved is not None
    assert resolved.name == "model.safetensors"  # largest


def test_resolve_across_multiple_snapshots(hub: Path) -> None:
    _make_snapshot(hub, "org/r", "sha-old", {"old.gguf": 100})
    _make_snapshot(hub, "org/r", "sha-new", {"new.gguf": 9999})
    entry = migrate_haloai.AllowEntry(
        id="x", name="x", capabilities=(), license="", hf_repo="org/r"
    )
    assert migrate_haloai.resolve_entry(entry, hub).name == "new.gguf"


# ── build_model ───────────────────────────────────────────────────────────────


def test_build_model_validates_via_pydantic(hub: Path) -> None:
    snap = _make_snapshot(hub, "org/r", "s", {"m.gguf": 1234})
    entry = migrate_haloai.AllowEntry(
        id="my-model",
        name="My Model",
        capabilities=("chat", "code"),
        license="Apache-2.0",
        hf_repo="org/r",
    )
    m = migrate_haloai.build_model(entry, snap / "m.gguf")
    assert isinstance(m, Model)
    assert m.id == "my-model"
    assert m.size_bytes == 1234
    assert m.capabilities == ["chat", "code"]
    assert "migrated" in m.tags


# ── DEFAULT_ALLOWLIST ─────────────────────────────────────────────────────────


def test_default_allowlist_has_fourteen_entries() -> None:
    assert len(migrate_haloai.DEFAULT_ALLOWLIST) == 14


def test_default_allowlist_ids_are_unique() -> None:
    ids = [e.id for e in migrate_haloai.DEFAULT_ALLOWLIST]
    assert len(ids) == len(set(ids))


def test_default_allowlist_targets_curated_repos() -> None:
    repos = {e.hf_repo for e in migrate_haloai.DEFAULT_ALLOWLIST}
    # Confidence checks the specific big-LLMs the user named are present.
    assert "unsloth/Qwen3-Coder-Next-GGUF" in repos
    assert "amd/Qwen3-Coder-Next-MXFP4" in repos
    assert "cpatonn/Qwen3-Next-80B-A3B-Thinking-AWQ-4bit" in repos
    assert "eousphoros/kappa-20b-131k-mxfp4" in repos
    assert "mradermacher/kappa-20b-131k-i1-GGUF" in repos


# ── load_allowlist ────────────────────────────────────────────────────────────


def test_load_allowlist_default_is_built_in() -> None:
    assert migrate_haloai.load_allowlist(None) is migrate_haloai.DEFAULT_ALLOWLIST


def test_load_allowlist_from_toml(tmp_path: Path) -> None:
    p = tmp_path / "allow.toml"
    p.write_text(
        """
[[models]]
id = "custom-1"
name = "Custom One"
capabilities = ["chat"]
license = "MIT"
hf_repo = "user/custom-1"
hf_pattern = "*.gguf"
""",
        encoding="utf-8",
    )
    out = migrate_haloai.load_allowlist(p)
    assert len(out) == 1
    assert out[0].id == "custom-1"
    assert out[0].license == "MIT"


def test_load_allowlist_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(migrate_haloai.MigrationError, match="not found"):
        migrate_haloai.load_allowlist(tmp_path / "nope.toml")


# ── migrate() ─────────────────────────────────────────────────────────────────


def _two_repo_hub(tmp_path: Path) -> tuple[Path, Path]:
    hub = tmp_path / "hub"
    hub.mkdir()
    _make_snapshot(hub, "unsloth/Qwen3.5-4B-GGUF", "s1", {"Qwen3.5-4B-UD-Q4.gguf": 5000})
    _make_snapshot(hub, "unsloth/Qwen3.6-27B-GGUF", "s2", {"Qwen3.6-27B-Q5.gguf": 9999})
    return hub, tmp_path / "out"


def test_migrate_writes_validated_registry(tmp_path: Path) -> None:
    hub, output = _two_repo_hub(tmp_path)
    # Subset allow-list — just the two we have.
    allowlist = (
        migrate_haloai.AllowEntry(
            id="qwen3.5-4b",
            name="Qwen3.5 4B",
            capabilities=("chat",),
            license="Apache-2.0",
            hf_repo="unsloth/Qwen3.5-4B-GGUF",
        ),
        migrate_haloai.AllowEntry(
            id="qwen3.6-27b",
            name="Qwen3.6 27B",
            capabilities=("chat",),
            license="Apache-2.0",
            hf_repo="unsloth/Qwen3.6-27B-GGUF",
        ),
    )
    summary = migrate_haloai.migrate(
        hub_root=hub,
        output=output,
        allowlist=allowlist,
        dry_run=False,
        force=False,
    )
    assert summary.resolved == ["qwen3.5-4b", "qwen3.6-27b"]
    assert summary.skipped == []
    registry = output / "var" / "lib" / "hal0" / "registry" / "registry.toml"
    assert registry.is_file()
    with registry.open("rb") as f:
        data = tomllib.load(f)
    assert set(data["models"].keys()) == {"qwen3.5-4b", "qwen3.6-27b"}
    # Each entry round-trips through pydantic.
    for mid, payload in data["models"].items():
        Model.model_validate({"id": mid, **payload})


def test_missing_model_is_skipped_and_warned(tmp_path: Path) -> None:
    hub, output = _two_repo_hub(tmp_path)
    allowlist = (
        migrate_haloai.AllowEntry(
            id="real",
            name="Real",
            capabilities=("chat",),
            license="Apache-2.0",
            hf_repo="unsloth/Qwen3.5-4B-GGUF",
        ),
        migrate_haloai.AllowEntry(
            id="ghost",
            name="Ghost",
            capabilities=("chat",),
            license="Apache-2.0",
            hf_repo="not/on-disk",
        ),
    )
    summary = migrate_haloai.migrate(
        hub_root=hub,
        output=output,
        allowlist=allowlist,
        dry_run=False,
        force=False,
    )
    assert summary.resolved == ["real"]
    assert summary.skipped == ["ghost"]


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    hub, output = _two_repo_hub(tmp_path)
    allowlist = (
        migrate_haloai.AllowEntry(
            id="qwen3.5-4b",
            name="Qwen3.5 4B",
            capabilities=("chat",),
            license="Apache-2.0",
            hf_repo="unsloth/Qwen3.5-4B-GGUF",
        ),
    )
    summary = migrate_haloai.migrate(
        hub_root=hub,
        output=output,
        allowlist=allowlist,
        dry_run=True,
        force=False,
    )
    assert summary.output_path is None
    assert not output.exists()


def test_missing_hub_root_raises(tmp_path: Path) -> None:
    with pytest.raises(migrate_haloai.MigrationError, match="hub root"):
        migrate_haloai.migrate(
            hub_root=tmp_path / "nope",
            output=tmp_path / "out",
            allowlist=(),
            dry_run=False,
            force=False,
        )


def test_refuses_to_clobber_without_force(tmp_path: Path) -> None:
    hub, output = _two_repo_hub(tmp_path)
    output.mkdir(parents=True, exist_ok=True)
    (output / "preexisting").write_text("hi", encoding="utf-8")
    with pytest.raises(migrate_haloai.MigrationError, match="not empty"):
        migrate_haloai.migrate(
            hub_root=hub,
            output=output,
            allowlist=(),
            dry_run=False,
            force=False,
        )


def test_force_clobbers_existing_output(tmp_path: Path) -> None:
    hub, output = _two_repo_hub(tmp_path)
    output.mkdir(parents=True, exist_ok=True)
    (output / "preexisting").write_text("hi", encoding="utf-8")
    summary = migrate_haloai.migrate(
        hub_root=hub,
        output=output,
        allowlist=(
            migrate_haloai.AllowEntry(
                id="qwen3.5-4b",
                name="Qwen3.5 4B",
                capabilities=("chat",),
                license="Apache-2.0",
                hf_repo="unsloth/Qwen3.5-4B-GGUF",
            ),
        ),
        dry_run=False,
        force=True,
    )
    assert summary.output_path is not None
    assert not (output / "preexisting").exists()


# ── render_registry round-trip ────────────────────────────────────────────────


def test_render_registry_strips_id_from_per_model_dict() -> None:
    m = Model(id="abc", name="A", path="/x", license="Apache-2.0", capabilities=["chat"])
    blob = migrate_haloai.render_registry([m])
    parsed = tomllib.loads(blob.decode("utf-8"))
    assert "abc" in parsed["models"]
    assert "id" not in parsed["models"]["abc"]
    assert parsed["models"]["abc"]["name"] == "A"

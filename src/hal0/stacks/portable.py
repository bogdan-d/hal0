"""Portable stacks — export/import/snapshot (spec §3/§4/§6).

Export embeds a stack's referenced profiles + model METADATA (never weights,
never host paths) into a self-contained ``.hal0stack.json`` envelope with a
content checksum. Import validates + classifies model refs (present / pullable
/ unresolvable) + reconciles profiles + creates the stack. Snapshot reads the
live config into a StackConfig. Pure functions — the caller stamps ``exported_at``
and injects the registry, so there is no clock or hidden global here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from hal0 import __version__
from hal0.config.loader import load_profiles_config
from hal0.config.schema import StackConfig, StackModelMeta
from hal0.registry.store import ModelRegistry

ENVELOPE_KIND = "hal0.stack"


def _referenced_model_ids(stack: StackConfig) -> set[str]:
    """Every model id a stack references — slot primaries + capability rows."""
    ids: set[str] = set()
    for entry in stack.slots:
        if entry.model:
            ids.add(entry.model)
        for row in entry.capabilities:
            if row.model:
                ids.add(row.model)
    return ids


def _referenced_profile_names(stack: StackConfig) -> set[str]:
    """Every profile name a stack's slots reference."""
    return {entry.profile for entry in stack.slots if entry.profile}


def embed_references(
    stack: StackConfig,
    *,
    registry: ModelRegistry,
    profiles_path: Path | None = None,
) -> StackConfig:
    """Return a copy of ``stack`` with ``models``/``profiles`` populated.

    Model metadata is the transport-safe subset of the registry ``Model``;
    ``mmproj`` is reduced to a presence marker so a host path never travels.
    Models absent from the registry are embedded as a bare-id ``StackModelMeta``
    so the importer still sees the reference (and reports it unresolvable).
    Referenced profiles are embedded verbatim from the live profile catalog.
    ``hal0_version`` is stamped for provenance.
    """
    models: dict[str, StackModelMeta] = {}
    for mid in sorted(_referenced_model_ids(stack)):
        if registry.has(mid):
            m = registry.get(mid)
            models[mid] = StackModelMeta(
                id=m.id,
                name=m.name,
                hf_repo=m.hf_repo,
                hf_filename=m.hf_filename,
                size_bytes=m.size_bytes,
                capabilities=list(m.capabilities),
                backends=list(m.backends),
                mmproj="present" if m.mmproj else None,
            )
        else:
            models[mid] = StackModelMeta(id=mid)

    pcfg = load_profiles_config(profiles_path)
    profiles = {
        name: pcfg.profile[name]
        for name in sorted(_referenced_profile_names(stack))
        if name in pcfg.profile
    }

    return stack.model_copy(
        update={"profiles": profiles, "models": models, "hal0_version": __version__}
    )


def _checksum(stack_body: dict[str, Any]) -> str:
    """sha256 over the canonical stack body — deterministic, order-independent."""
    payload = json.dumps(stack_body, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def export_envelope(
    stack: StackConfig,
    *,
    exported_at: str,
    registry: ModelRegistry,
    profiles_path: Path | None = None,
) -> dict[str, Any]:
    """Build the ``.hal0stack.json`` envelope dict for ``stack``.

    ``exported_at`` is caller-supplied (no clock here). The checksum covers the
    embedded stack body only — re-exporting the same stack yields the same
    checksum regardless of ``exported_at``.
    """
    embedded = embed_references(stack, registry=registry, profiles_path=profiles_path)
    body = embedded.model_dump(mode="python", exclude_none=True)
    return {
        "kind": ENVELOPE_KIND,
        "schema_version": embedded.schema_version,
        "hal0_version": embedded.hal0_version,
        "exported_at": exported_at,
        "checksum": _checksum(body),
        "stack": body,
    }

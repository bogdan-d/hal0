"""StackApplyEngine — translate a StackConfig into an atomic slot-config change.

Phase A of the Stacks apply flow (spec §5): reconcile each stack slot entry
onto its ``slots/<slot>.toml`` and assemble ONE ``hal0.slot_config.ChangeSet``
spanning every touched file, then commit it through the verified
``SlotConfigStore`` (atomic write + per-file rollback). Compute-only ``plan()``
backs the dashboard's dry-run diff preview.

Out of scope here (PR-2b): slot lifecycle convergence (load/swap/unload) and
capability-child (embed/stt/tts/rerank/vision) routing through the
CapabilityOrchestrator.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hal0.config import paths
from hal0.config.schema import StackConfig, StackSlotEntry
from hal0.model_meta import canonical_device, device_to_legacy_backend
from hal0.slot_config import ChangeSet, FileState, SlotConfigStore

log = logging.getLogger(__name__)


def _read_toml_or_none(path: Path) -> dict[str, Any] | None:
    """Read a TOML file as a raw dict; ``None`` when it doesn't exist.

    Local mirror of ``hal0.slot_config._read_toml_or_none`` (kept local to
    avoid importing a sibling module's private; the body is trivial I/O).
    """
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return None


@dataclass(frozen=True)
class StackChangePlan:
    """The compute-only result of planning a stack apply.

    ``change_set`` is consumed by :meth:`StackApplyEngine.apply_config` (commit)
    and by the drift hasher; ``summary`` is human-readable diff lines for the
    dry-run preview.
    """

    stack_slug: str
    change_set: ChangeSet
    summary: list[str]


class StackApplyEngine:
    """Reconcile a StackConfig onto slot TOMLs as one ChangeSet."""

    def __init__(
        self,
        *,
        slots_dir: Path | None = None,
        store: SlotConfigStore | None = None,
    ) -> None:
        self._slots_dir = Path(slots_dir) if slots_dir else None
        self._store = store or SlotConfigStore(slots_dir=slots_dir)

    def _slot_path(self, slot_name: str) -> Path:
        base = self._slots_dir or paths.slots_config_dir()
        return base / f"{slot_name}.toml"

    # ── plan (compute-only) ──────────────────────────────────────────────────

    def plan(self, slug: str, stack: StackConfig) -> StackChangePlan:
        """Compute the post-state for ``stack``. Writes NOTHING.

        Only entries that carry a primary ``model`` and whose slot TOML already
        exists are reconciled (slot creation is SlotManager's job, out of 2a
        scope). For every other entry ``after == before``.
        """
        befores: list[FileState] = []
        afters: list[FileState] = []
        summary: list[str] = []

        for entry in stack.slots:
            if not entry.model:
                continue
            path = self._slot_path(entry.slot)
            before = _read_toml_or_none(path)
            after = self._reconciled_stack_slot(before, entry)
            befores.append(FileState(path=path, data=before))
            afters.append(FileState(path=path, data=after))
            if before != after:
                summary.append(self._summarize(entry.slot, before, after))

        return StackChangePlan(
            stack_slug=slug,
            change_set=ChangeSet(before=tuple(befores), after=tuple(afters)),
            summary=summary,
        )

    def _reconciled_stack_slot(
        self, before: dict[str, Any] | None, entry: StackSlotEntry
    ) -> dict[str, Any] | None:
        """Project a stack slot entry onto the existing slot TOML dict.

        Deep-merges the nested ``[model]``/``[server]`` tables so sibling keys
        (``context_size`` etc.) survive. Writes both the v0.2 ``device`` and the
        one-release-legacy ``backend`` alias via :mod:`hal0.model_meta`. Returns
        ``before`` unchanged when the slot file is absent (creation is out of
        2a scope).
        """
        if before is None:
            return None
        after = dict(before)

        if entry.model:
            model = dict(after.get("model") or {})
            model["default"] = entry.model
            after["model"] = model
        if entry.device:
            device = canonical_device(entry.device)
            if device:
                after["device"] = device
                legacy = device_to_legacy_backend(device)
                if legacy:
                    after["backend"] = legacy
        if entry.provider:
            after["provider"] = entry.provider
        if entry.profile is not None:
            after["profile"] = entry.profile
        if entry.role is not None:
            after["role"] = entry.role
        # ``vision`` is a plain bool (no inherit) → declaratively written.
        after["vision"] = entry.vision
        if entry.mtp is not None:
            after["mtp"] = entry.mtp
        if entry.enable_thinking is not None:
            after["enable_thinking"] = entry.enable_thinking
        if entry.server_extra_args is not None:
            server = dict(after.get("server") or {})
            server["extra_args"] = entry.server_extra_args
            after["server"] = server
        return after

    @staticmethod
    def _summarize(
        slot: str, before: dict[str, Any] | None, after: dict[str, Any] | None
    ) -> str:
        b_model = (before or {}).get("model", {}).get("default") if before else None
        a_model = (after or {}).get("model", {}).get("default") if after else None
        if b_model != a_model:
            return f"{slot}: model {b_model or '∅'} → {a_model or '∅'}"
        return f"{slot}: config updated"

    # ── apply (commit) ───────────────────────────────────────────────────────

    def apply_config(self, plan: StackChangePlan) -> None:
        """Commit ``plan.change_set`` to disk atomically.

        Delegates to ``SlotConfigStore.commit``: each file is written
        tmpfile+fsync+rename; a mid-set failure restores every already-written
        file to its ``before`` snapshot and re-raises — disk is never left
        half-reconciled. A no-op ChangeSet (nothing changed) writes nothing.
        """
        self._store.commit(plan.change_set)

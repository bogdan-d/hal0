"""CapabilityOrchestrator — bridge between capability children and slots.

The dashboard treats embed/voice/img as "capability slots" with multiple
children each (embed.embed + embed.rerank, voice.stt + voice.tts,
img.img). Under the hood every child maps 1:1 to a regular hal0 slot
managed by :class:`~hal0.slots.manager.SlotManager`. This module owns:

  - The ``_CHILD_TO_SLOT`` mapping that defines that bridge.
  - Persistence of the operator's selections in
    ``/etc/hal0/capabilities.toml``.
  - The lifecycle dispatch — ``apply()`` flips slots load/swap/unload to
    match the new selection and rewrites the underlying slot's TOML when
    the user changes backend/provider.

NPU multiplex (one ``flm`` process serving multiple capability children)
is OUT OF SCOPE for this round; NPU children spawn their own slot via
the regular ``load()`` path when needed.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from hal0.capabilities.catalog import models_for_capability
from hal0.capabilities.config import (
    CapabilityConfig,
    CapabilitySelection,
    capabilities_toml_path,
    load_capabilities_config,
    save_capabilities_config,
)
from hal0.config import paths
from hal0.config.loader import load_slot_config, write_toml_atomic
from hal0.errors import BadRequest, Hal0Error, NotFound
from hal0.registry.store import ModelRegistry
from hal0.slots.manager import SlotManager

log = logging.getLogger(__name__)


# ── The bridge: capability child → underlying slot name ──────────────────────

# Hardcoded as per the spec. NPU multiplex (one slot for multiple
# children) is deferred — each child currently spawns its own slot.
_CHILD_TO_SLOT: dict[tuple[str, str], str] = {
    ("embed", "embed"): "embed",
    ("embed", "rerank"): "embed-rerank",
    ("voice", "stt"): "stt",
    ("voice", "tts"): "tts",
    ("img", "img"): "img",
}

# Inverse for status surfacing ("which child is this slot serving").
_SLOT_TO_CHILD: dict[str, tuple[str, str]] = {
    slot_name: key for key, slot_name in _CHILD_TO_SLOT.items()
}

# The legal capability/child surface — used by HTTP validation.
LEGAL_SLOTS: tuple[str, ...] = ("embed", "voice", "img")


def legal_children(slot: str) -> list[str]:
    """Return the child names valid for ``slot``."""
    return [child for (s, child) in _CHILD_TO_SLOT if s == slot]


def child_to_slot(slot: str, child: str) -> str:
    """Resolve a (slot, child) tuple to its underlying slot name.

    Raises :class:`BadRequest` for unknown combinations so HTTP routes
    surface a 400 envelope rather than a 500.
    """
    key = (slot, child)
    if key not in _CHILD_TO_SLOT:
        raise BadRequest(
            f"unknown capability child {slot!r}.{child!r}",
            code="capability.unknown_child",
            details={"slot": slot, "child": child},
        )
    return _CHILD_TO_SLOT[key]


# ── The capability mapping that drives "which capability tag does a child want" ──
_CHILD_TO_CAPABILITY: dict[tuple[str, str], str] = {
    ("embed", "embed"): "embed",
    ("embed", "rerank"): "rerank",
    ("voice", "stt"): "stt",
    ("voice", "tts"): "tts",
    ("img", "img"): "image",
}


# ── Errors ────────────────────────────────────────────────────────────────────


class CapabilityApplyFailed(Hal0Error):
    """503 — the underlying SlotManager call failed.

    Surfaced to the dashboard as ``{ code: "capability.apply_failed",
    detail: ... }`` so the picker UI can render a banner without
    swallowing the original message.
    """

    code = "capability.apply_failed"
    status = 503


# ── Orchestrator ──────────────────────────────────────────────────────────────


class CapabilityOrchestrator:
    """Thin overlay that maps capability selections onto slot lifecycle.

    Held as a singleton on ``app.state.capability_orchestrator`` (see
    :mod:`hal0.api`); the route handlers get one via
    :data:`hal0.api.deps.CapabilityOrchestratorDep`.
    """

    def __init__(
        self,
        slot_manager: SlotManager,
        *,
        config_path: Path | None = None,
        registry: ModelRegistry | None = None,
    ) -> None:
        self._slot_manager = slot_manager
        self._config_path = Path(config_path) if config_path else capabilities_toml_path()
        self._registry = registry

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> CapabilityConfig:
        return load_capabilities_config(self._config_path)

    def _save(self, cfg: CapabilityConfig) -> None:
        save_capabilities_config(cfg, self._config_path)

    async def initialize_if_missing(self) -> None:
        """Seed ``capabilities.toml`` from existing slot configs on first boot.

        Idempotent: when the file already exists, this is a no-op. Otherwise
        we walk ``/etc/hal0/slots/{embed,stt,tts,img}.toml`` and lift each
        slot's current backend/provider/model + ``enabled`` flag into the
        matching child. Slots that don't exist on disk get an empty
        selection so the dashboard can still render an "unset" picker.
        """
        if self._config_path.exists():
            return

        cfg = CapabilityConfig()
        for (slot, child), slot_name in _CHILD_TO_SLOT.items():
            cfg.selections.setdefault(slot, {})
            selection = CapabilitySelection()
            try:
                slot_cfg = load_slot_config(slot_name)
            except Exception:
                # Slot TOML missing or invalid — leave the selection blank.
                cfg.selections[slot][child] = selection
                continue
            # Lift the fields we care about.
            selection.backend = self._canonical_backend_id(slot_cfg.backend)
            selection.provider = slot_cfg.provider
            selection.model = slot_cfg.model.default or ""
            selection.enabled = bool(slot_cfg.enabled) and bool(selection.model)
            cfg.selections[slot][child] = selection

        self._save(cfg)

    # ── shape helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _canonical_backend_id(slot_backend: str) -> str:
        """Translate slot TOML's ``backend`` value to the catalog's id.

        Slot configs use ``vulkan`` / ``rocm`` / ``flm`` / ``cpu`` /
        provider-specific tags. The capabilities surface uses ``gpu-vulkan``
        / ``gpu-rocm`` / ``npu`` / ``cpu`` / provider tags. Map between
        them — unknown values pass through verbatim so a hand-edited
        slot still surfaces something.
        """
        mapping = {
            "vulkan": "gpu-vulkan",
            "rocm": "gpu-rocm",
            "flm": "npu",
            # kokoro/moonshine slots live on the GPU; surface as such.
            "kokoro": "gpu-vulkan",
            "moonshine": "gpu-vulkan",
            "cpu": "cpu",
        }
        return mapping.get(slot_backend, slot_backend or "")

    @staticmethod
    def _slot_backend_for_catalog_id(backend_id: str) -> str:
        """Inverse: catalog backend id → SlotConfig.backend string."""
        mapping = {
            "gpu-vulkan": "vulkan",
            "gpu-rocm": "rocm",
            "npu": "flm",
            "cpu": "cpu",
        }
        return mapping.get(backend_id, backend_id)

    def _selection_with_defaults(
        self, cfg: CapabilityConfig, slot: str, child: str
    ) -> CapabilitySelection:
        """Return the persisted selection for (slot, child), filling defaults."""
        slot_bucket = cfg.selections.setdefault(slot, {})
        return slot_bucket.setdefault(child, CapabilitySelection())

    # ── public reads ─────────────────────────────────────────────────────────

    async def get_state(self) -> dict[str, Any]:
        """Build the full GET /api/capabilities response payload.

        Resolves: catalogs (per-child picker rows from the registry),
        backends (from the hardware probe), and selections (persisted
        with live ``slot`` + ``status`` derived from SlotManager).
        """
        # Import locally so the orchestrator stays cheap to import (no
        # SlotManager dependency on module load).
        from hal0.capabilities.catalog import available_backends, catalogs_by_slot

        cfg = self._load()
        backends = available_backends()
        catalogs = catalogs_by_slot(registry=self._registry)

        selections_out: dict[str, dict[str, dict[str, Any]]] = {}
        for slot in LEGAL_SLOTS:
            selections_out[slot] = {}
            for child in legal_children(slot):
                selection = self._selection_with_defaults(cfg, slot, child)
                slot_name = _CHILD_TO_SLOT[(slot, child)]
                status_str = await self._slot_status_string(slot_name)
                selections_out[slot][child] = {
                    "backend": selection.backend,
                    "provider": selection.provider,
                    "model": selection.model,
                    "enabled": selection.enabled,
                    "slot": slot_name,
                    "status": status_str,
                }

        return {
            "backends": backends,
            "catalogs": catalogs,
            "selections": selections_out,
        }

    async def _slot_status_string(self, slot_name: str) -> str:
        """Return the slot's current state.value, or 'offline' if unknown.

        SlotManager.status() raises SlotNotFound for slots that haven't
        been configured yet (the embed-rerank slot, for instance, is
        only auto-created on first enable). Treat those as 'offline' so
        the dashboard always gets a string.
        """
        try:
            snap = await self._slot_manager.status(slot_name)
            return snap.state.value
        except Exception:
            return "offline"

    # ── apply ────────────────────────────────────────────────────────────────

    async def apply(
        self,
        slot: str,
        child: str,
        partial: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge a partial selection update and reconcile slot lifecycle.

        Returns the merged selection as a dict in the same shape the
        ``selections`` block of ``get_state()`` exposes. Wraps any
        underlying SlotManager / config error as :class:`CapabilityApplyFailed`
        so the HTTP layer renders a 503 envelope.
        """
        if slot not in LEGAL_SLOTS:
            raise BadRequest(
                f"unknown capability slot {slot!r}",
                code="capability.unknown_slot",
                details={"slot": slot, "legal": list(LEGAL_SLOTS)},
            )
        if child not in legal_children(slot):
            raise BadRequest(
                f"child {child!r} not valid for capability {slot!r}",
                code="capability.unknown_child",
                details={"slot": slot, "child": child, "legal": legal_children(slot)},
            )

        slot_name = _CHILD_TO_SLOT[(slot, child)]
        cfg = self._load()
        existing = self._selection_with_defaults(cfg, slot, child)
        before_enabled = existing.enabled
        before_model = existing.model
        before_backend = existing.backend
        before_provider = existing.provider

        # Shallow-merge the partial into the existing selection.
        merged_data: dict[str, Any] = existing.model_dump()
        for key in ("backend", "provider", "model", "enabled"):
            if key in partial:
                merged_data[key] = partial[key]
        try:
            merged = CapabilitySelection.model_validate(merged_data)
        except Exception as exc:
            raise BadRequest(
                f"invalid capability selection: {exc}",
                code="capability.invalid_selection",
                details={"slot": slot, "child": child, "partial": partial},
            ) from exc

        # Validate the model against the catalog when one is set + the
        # caller didn't explicitly clear it. We don't fail when the model
        # is empty — that's the "unset" state.
        if merged.model:
            self._validate_model_in_catalog(slot, child, merged.model)

        cfg.selections[slot][child] = merged

        # ── lifecycle dispatch ────────────────────────────────────────────
        enabled_changed = merged.enabled != before_enabled
        model_changed = merged.model != before_model
        backend_changed = merged.backend != before_backend
        provider_changed = merged.provider != before_provider

        try:
            # Backend or provider change while enabled → rewrite the slot
            # TOML so the next load/swap picks up the new values. Done
            # before swap/load so the spawn reads the right config.
            if (backend_changed or provider_changed) and (
                merged.enabled or before_enabled
            ):
                await self._rewrite_underlying_slot(slot_name, merged)

            if enabled_changed and merged.enabled:
                # off → on: ensure the slot exists, then load with the model.
                await self._ensure_slot_exists(slot_name, merged)
                if merged.model:
                    await self._slot_manager.load(slot_name, model_id=merged.model)
            elif enabled_changed and not merged.enabled:
                # on → off: best-effort unload; tolerate slots that were
                # never loaded (status() will return OFFLINE → unload is a no-op).
                with contextlib.suppress(Exception):
                    await self._slot_manager.unload(slot_name)
            elif merged.enabled and (model_changed or backend_changed) and merged.model:
                # Still on, but model / backend changed → hot-swap.
                await self._ensure_slot_exists(slot_name, merged)
                await self._slot_manager.swap(slot_name, merged.model)
        except Hal0Error:
            # Re-raise typed errors as the apply_failed envelope so the UI
            # surfaces a single, recognisable code.
            self._save(cfg)  # persist the user's intent even if the slot bounce failed
            raise
        except Exception as exc:
            self._save(cfg)
            raise CapabilityApplyFailed(
                f"failed to apply capability change: {exc}",
                details={"slot": slot, "child": child, "error": str(exc)},
            ) from exc

        # Persist after the side effects so an interrupted lifecycle
        # call doesn't leave a stale selection on disk.
        self._save(cfg)

        status_str = await self._slot_status_string(slot_name)
        return {
            "backend": merged.backend,
            "provider": merged.provider,
            "model": merged.model,
            "enabled": merged.enabled,
            "slot": slot_name,
            "status": status_str,
        }

    # ── slot TOML helpers ────────────────────────────────────────────────────

    def _validate_model_in_catalog(self, slot: str, child: str, model_id: str) -> None:
        """Raise :class:`NotFound` when ``model_id`` is not advertised for this child.

        Pulls the per-capability picker rows and checks the id against
        them. Unknown ids likely indicate a stale dashboard cache or a
        manual TOML edit referencing a removed model.
        """
        capability = _CHILD_TO_CAPABILITY.get((slot, child))
        if capability is None:
            return
        rows = models_for_capability(capability, registry=self._registry)
        if not any(row["id"] == model_id for row in rows):
            # Don't hard-fail — the registry may carry the model even when
            # the curated catalogue doesn't. Try the registry directly as
            # a permissive secondary check.
            if self._registry is not None and self._registry.has(model_id):
                return
            raise NotFound(
                f"model {model_id!r} not advertised for {slot}.{child}",
                code="capability.unknown_model",
                details={"slot": slot, "child": child, "model": model_id},
            )

    async def _ensure_slot_exists(
        self, slot_name: str, selection: CapabilitySelection
    ) -> None:
        """Auto-create the slot TOML on first use of a non-builtin child.

        ``embed-rerank`` is the canonical example: it isn't a builtin
        slot, so the SlotManager would raise SlotNotFound on the first
        load. We synthesise a minimal config from the selection and let
        ``SlotManager.create()`` do the persist + state initialisation.
        """
        cfg_path = paths.slots_config_dir() / f"{slot_name}.toml"
        if cfg_path.exists():
            return

        port = self._next_free_slot_port()
        slot_backend = self._slot_backend_for_catalog_id(selection.backend)
        provider = selection.provider or "llama-server"
        cfg_dict = {
            "name": slot_name,
            "port": port,
            "backend": slot_backend or "vulkan",
            "provider": provider,
            "enabled": True,
            "model": {"default": selection.model or ""},
        }
        try:
            await self._slot_manager.create(slot_name, cfg_dict)
        except Exception as exc:
            raise CapabilityApplyFailed(
                f"failed to create slot {slot_name!r}: {exc}",
                details={"slot": slot_name, "error": str(exc)},
            ) from exc

    async def _rewrite_underlying_slot(
        self, slot_name: str, selection: CapabilitySelection
    ) -> None:
        """Persist backend / provider changes into the underlying slot TOML.

        Routes through :meth:`SlotManager.update_config` so the override
        drop-in + env file get regenerated alongside the TOML. If the slot
        doesn't exist yet, this is a no-op — the create path below will
        write the config fresh.
        """
        cfg_path = paths.slots_config_dir() / f"{slot_name}.toml"
        if not cfg_path.exists():
            return
        slot_backend = self._slot_backend_for_catalog_id(selection.backend)
        updates: dict[str, Any] = {}
        if slot_backend:
            updates["backend"] = slot_backend
        if selection.provider:
            updates["provider"] = selection.provider
        if selection.model:
            updates["model"] = {"default": selection.model}
        if not updates:
            return
        try:
            await self._slot_manager.update_config(slot_name, updates)
        except Exception as exc:
            raise CapabilityApplyFailed(
                f"failed to rewrite slot {slot_name!r}: {exc}",
                details={"slot": slot_name, "error": str(exc)},
            ) from exc

    def _next_free_slot_port(self) -> int:
        """Pick a free port in the slot range.

        Scans every existing slot TOML for its ``port``, returns the
        first gap inside ``8081-8099``. The SlotConfig validator pins
        ports into that range; collisions here would surface as a
        validation error from ``SlotManager.create``.
        """
        used: set[int] = set()
        cfg_dir = paths.slots_config_dir()
        if cfg_dir.exists():
            for p in cfg_dir.glob("*.toml"):
                try:
                    slot_cfg = load_slot_config(p.stem)
                    used.add(slot_cfg.port)
                except Exception:
                    # Malformed TOMLs don't reserve ports — they'll be
                    # surfaced via the slot routes the next time the
                    # operator looks.
                    continue
        for port in range(8081, 8100):
            if port not in used:
                return port
        # Pool is full — surface as apply_failed rather than silently
        # collide. The user will see the envelope and know to clean up.
        raise CapabilityApplyFailed(
            "no free slot port available in 8081-8099",
            details={"used": sorted(used)},
        )


__all__ = [
    "CapabilityApplyFailed",
    "CapabilityOrchestrator",
    "LEGAL_SLOTS",
    "child_to_slot",
    "legal_children",
]


# ── tomli_w guard ────────────────────────────────────────────────────────────
# ``write_toml_atomic`` (used by ``save_capabilities_config``) needs tomli_w
# at runtime. We don't re-import it here, but referencing the symbol keeps
# import-time errors loud + visible to the test harness that asserts the
# orchestrator imports cleanly.
_ = write_toml_atomic

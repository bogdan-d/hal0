"""Catalog: available models per capability + available backends.

Two surfaces:

  - :func:`models_for_capability` reads :mod:`hal0.registry.curated`
    (and any registered :class:`~hal0.registry.store.ModelRegistry`
    entries) to produce a per-(backend, model) row for the dashboard
    picker. The same model id may appear once per backend it can run on
    — the picker uses ``backend`` as the secondary key.

  - :func:`available_backends` derives ``[npu (if XDNA), gpu-vulkan,
    gpu-rocm, cpu]`` from the cached hardware probe at
    ``/etc/hal0/hardware.json``.

Both helpers stay deliberately pure / synchronous — they're called from
``GET /api/capabilities`` on every load, so they must not hit the network
or invoke subprocesses. The registry + hardware probe layers already
cache the heavy work upstream.
"""

from __future__ import annotations

from typing import Any

from hal0.config.loader import load_hardware_info
from hal0.registry.curated import CURATED, CuratedModel, HaloaiModel
from hal0.registry.store import ModelRegistry


# ── Capability → child mappings ───────────────────────────────────────────────

# Capability strings that may appear on a Model / CuratedModel mapped to
# the child slot they should populate. Multiple capability tags can map
# to the same child (e.g. "stt" and "asr" both go to voice.stt).
_CAPABILITY_TO_CHILD: dict[str, tuple[str, str]] = {
    "embed": ("embed", "embed"),
    "rerank": ("embed", "rerank"),
    "stt": ("voice", "stt"),
    "asr": ("voice", "stt"),
    "tts": ("voice", "tts"),
    "image": ("img", "img"),
}

# Provider hints derived from a model's ``backend`` tag — used so the
# catalog rows can pre-fill the provider dropdown alongside the backend
# dropdown in the picker UI.
_BACKEND_TO_PROVIDER: dict[str, str] = {
    "flm": "flm",
    "llamacpp": "llama-server",
    "llama-server": "llama-server",
    "kokoro": "kokoro",
    "moonshine": "moonshine",
    "vibevoice": "kokoro",  # closest existing provider; the UI lets the user override
    "comfyui": "comfyui",
}


# ── Backends ──────────────────────────────────────────────────────────────────


def available_backends() -> list[dict[str, Any]]:
    """Return the list of backends this host can run, ordered.

    Order: NPU first (when XDNA is present), then GPU/Vulkan (always
    when a GPU is detected), then GPU/ROCm (only when the GPU is
    ``compute_capable``), then CPU as a guaranteed-available fallback.

    Each entry carries the fields the dashboard footer renders:
    ``id`` (stable key the selection writer expects), ``label`` (long
    name), ``short`` (badge text), ``provider`` (default provider for
    this backend), and ``multiplex`` (true for NPU/FLM where one
    process serves many models).
    """
    out: list[dict[str, Any]] = []
    try:
        hw = load_hardware_info()
    except Exception:
        # Probe missing or unreadable — fall back to CPU-only so the UI
        # still renders a usable picker.
        hw = None

    npu_present = bool(hw and hw.npu and hw.npu.present)
    primary_gpu = hw.gpus[0] if hw and hw.gpus else None

    if npu_present:
        out.append(
            {
                "id": "npu",
                "label": "NPU",
                "short": "NPU",
                "provider": "flm",
                "multiplex": True,
            }
        )

    if primary_gpu is not None:
        # Vulkan path — every detected GPU we surface is assumed Vulkan
        # capable. (Probe defaults vulkan_capable=False for non-AMD,
        # but every modern Linux GPU has Mesa Vulkan.)
        if primary_gpu.vulkan_capable or primary_gpu.vendor in {"amd", "nvidia", "intel"}:
            out.append(
                {
                    "id": "gpu-vulkan",
                    "label": "GPU (Vulkan)",
                    "short": "GPU/Vk",
                    "provider": "llama-server",
                    "multiplex": False,
                }
            )
        # ROCm path — only AMD GPUs with compute support light this up.
        if primary_gpu.vendor == "amd" and primary_gpu.compute_capable:
            out.append(
                {
                    "id": "gpu-rocm",
                    "label": "GPU (ROCm)",
                    "short": "GPU/ROCm",
                    "provider": "llama-server",
                    "multiplex": False,
                }
            )

    # CPU is always reachable; provider stays llama-server (the same
    # binary, run with --n-gpu-layers 0).
    out.append(
        {
            "id": "cpu",
            "label": "CPU",
            "short": "CPU",
            "provider": "llama-server",
            "multiplex": False,
        }
    )
    return out


def get_backend(backend_id: str) -> dict[str, Any] | None:
    """Return one backend descriptor by id, or ``None`` if not present."""
    for b in available_backends():
        if b["id"] == backend_id:
            return b
    return None


# ── Models per capability ─────────────────────────────────────────────────────


def _model_capabilities(entry: CuratedModel | HaloaiModel | Any) -> list[str]:
    """Best-effort capability extraction across the catalog shapes.

    Curated entries expose a single ``capability`` string; haloai-seeded
    entries do the same. Registry-loaded :class:`~hal0.registry.model.Model`
    rows carry a ``capabilities`` list. Either shape works.
    """
    caps: list[str] = []
    cap = getattr(entry, "capability", None)
    if isinstance(cap, str) and cap:
        caps.append(cap)
    cap_list = getattr(entry, "capabilities", None)
    if isinstance(cap_list, list):
        for c in cap_list:
            if isinstance(c, str) and c and c not in caps:
                caps.append(c)
    return caps


def _backend_variants(entry: Any) -> list[str]:
    """Return the canonical backend ids this entry can run under.

    Curated and haloai entries carry a single ``backend`` string tag
    (e.g. ``"flm"`` or ``"llamacpp"``). Registry entries may carry a
    ``backends`` list. We map those to the stable backend ids used by
    :func:`available_backends`. Llama.cpp-compatible entries fan out
    across every GPU backend the host advertises (gpu-vulkan / gpu-rocm
    / cpu) — that's the picker's "this GGUF runs everywhere" UX.
    """
    raw: list[str] = []
    backend = getattr(entry, "backend", None)
    if isinstance(backend, str) and backend:
        raw.append(backend)
    backend_list = getattr(entry, "backends", None)
    if isinstance(backend_list, list):
        for b in backend_list:
            if isinstance(b, str) and b and b not in raw:
                raw.append(b)

    # ── Defaults by entry shape ───────────────────────────────────────────
    # Curated image entries (the FirstRun image picks) carry no ``backend``
    # field — :class:`CuratedModel` has no such attribute. Treat the
    # presence of ``comfyui_subdir`` or ``capability == "image"`` as a
    # signal to route through ComfyUI, which fan-outs to gpu-vulkan + cpu
    # via the provider-runtime branch below.
    if not raw:
        comfy_subdir = getattr(entry, "comfyui_subdir", "") or ""
        cap_str = getattr(entry, "capability", "") or ""
        if comfy_subdir or cap_str == "image":
            raw.append("comfyui")

    out: list[str] = []
    for b in raw:
        low = b.lower()
        if low in {"flm", "npu"}:
            if "npu" not in out:
                out.append("npu")
        elif low in {"vulkan", "gpu-vulkan", "llamacpp", "llama-server"}:
            # Llama.cpp-compatible — fan out to every GPU/CPU backend
            # the host actually advertises so the picker shows what's
            # really runnable here.
            host_backends = {b["id"] for b in available_backends()}
            for candidate in ("gpu-vulkan", "gpu-rocm", "cpu"):
                if candidate in host_backends and candidate not in out:
                    out.append(candidate)
        elif low in {"rocm", "gpu-rocm"}:
            if "gpu-rocm" not in out:
                out.append("gpu-rocm")
        elif low in {"cpu"}:
            if "cpu" not in out:
                out.append("cpu")
        elif low in {"kokoro", "moonshine", "vibevoice", "comfyui"}:
            # Provider-specific runtimes pin to the GPU/Vulkan backend
            # on this host (they ship as their own container but the
            # operator-facing backend is "the GPU").
            host_backends = {b["id"] for b in available_backends()}
            for candidate in ("gpu-vulkan", "cpu"):
                if candidate in host_backends and candidate not in out:
                    out.append(candidate)
        # Unknown backend strings fall through silently — they're
        # surfaced for debugging via the registry view, not here.
    return out


def _provider_for_backend(entry_backend: str, backend_id: str) -> str:
    """Pick the provider that pairs with this backend / entry combo."""
    if backend_id == "npu":
        return "flm"
    if entry_backend in _BACKEND_TO_PROVIDER:
        return _BACKEND_TO_PROVIDER[entry_backend]
    # Default for llama.cpp-compatible models.
    return "llama-server"


def _size_gb(entry: Any) -> float:
    """Return the model's on-disk size in GB, best effort."""
    size_gb = getattr(entry, "size_gb", None)
    if isinstance(size_gb, (int, float)) and size_gb > 0:
        return float(size_gb)
    size_bytes = getattr(entry, "size_bytes", None)
    if isinstance(size_bytes, (int, float)) and size_bytes > 0:
        return round(float(size_bytes) / (1024**3), 2)
    return 0.0


def _entry_to_row(
    entry: Any, backend_id: str, capabilities: list[str]
) -> dict[str, Any]:
    """Project one (entry, backend) pair into a picker row."""
    raw_backend = getattr(entry, "backend", "") or ""
    return {
        "id": entry.id,
        "backend": backend_id,
        "provider": _provider_for_backend(raw_backend, backend_id),
        "size_gb": _size_gb(entry),
        "capabilities": capabilities,
    }


def _iter_registry_models(registry: ModelRegistry | None) -> list[Any]:
    """Return the registry's entries, or ``[]`` if no registry available."""
    if registry is None:
        return []
    try:
        return list(registry.list())
    except Exception:
        return []


def models_for_capability(
    capability: str,
    *,
    registry: ModelRegistry | None = None,
) -> list[dict[str, Any]]:
    """Return picker rows for one capability child ('embed' / 'rerank' / …).

    Walks :data:`CURATED` (curated picks + the haloai seed) plus the
    optional :class:`ModelRegistry`. Each compatible model contributes one
    row per backend it can run on, so the dashboard can show "the same
    nomic-embed model on Vulkan and CPU" as two rows.
    """
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    candidates: list[Any] = list(CURATED) + _iter_registry_models(registry)

    for entry in candidates:
        caps = _model_capabilities(entry)
        if capability not in caps:
            continue
        for backend_id in _backend_variants(entry):
            key = (str(entry.id), backend_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append(_entry_to_row(entry, backend_id, caps))
    return rows


def catalogs_by_slot(
    *, registry: ModelRegistry | None = None
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Return ``{ slot: { child: [picker_rows] } }`` for the dashboard.

    Mirrors the capability layout the orchestrator hard-codes — embed has
    two children (embed, rerank), voice has two (stt, tts), img has one.

    The ``chat`` bucket is included so backend-card UIs (notably
    :file:`ui/src/components/capabilities/NPUBackendCard.vue`) can walk
    every ``(slot, capability)`` pair when listing NPU-capable models —
    without this entry chat-on-NPU models would be invisible to the
    "+ load NPU model" picker (chat lives in the dedicated ``primary``
    slot, not in a capability slot). Operator selection for chat still
    flows through the primary slot config, NOT through capability apply.
    """
    return {
        "embed": {
            "embed": models_for_capability("embed", registry=registry),
            "rerank": models_for_capability("rerank", registry=registry),
        },
        "voice": {
            "stt": models_for_capability("stt", registry=registry),
            "tts": models_for_capability("tts", registry=registry),
        },
        "img": {
            "img": models_for_capability("image", registry=registry),
        },
        "chat": {
            "chat": models_for_capability("chat", registry=registry),
        },
    }


__all__ = [
    "available_backends",
    "catalogs_by_slot",
    "get_backend",
    "models_for_capability",
]

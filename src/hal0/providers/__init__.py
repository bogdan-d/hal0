"""hal0.providers — Inference backend abstraction layer.

Each Provider is a stateless class that knows how to build the environment
file, start command, and ContainerSpec for one backend type.  The Provider
ABC is the contract between SlotManager and the concrete backends.

v1 providers:
    LlamaServerProvider  — llama.cpp (Vulkan default, ROCm opt-in)
    FLMProvider          — AMD NPU (optional, Strix Halo only)
    MoonshineProvider    — Moonshine STT (CPU/Vulkan)
    KokoroProvider       — Kokoro TTS (CPU/Vulkan)

Port targets: haloai lib/providers/ (base.py, llama_server.py, flm.py).
Moonshine + Kokoro are new wrappers around haloai voice servers.
See PLAN.md §1, §3 and ARCHITECTURE.md §Key boundaries.
"""

from __future__ import annotations

from hal0.providers.base import ContainerSpec, Provider
from hal0.providers.comfyui import ComfyUIProvider
from hal0.providers.flm import FLMProvider
from hal0.providers.kokoro import KokoroProvider
from hal0.providers.llama_server import LlamaServerProvider
from hal0.providers.moonshine import MoonshineProvider

# Provider name → singleton instance.  Providers are stateless (per the
# ABC contract), so one instance per process is enough.  SlotManager
# itself stays provider-agnostic; the unit-template renderer (which is
# logically "provider-systemd glue") is the only caller of get_provider.
_PROVIDERS: dict[str, Provider] = {
    "llama-server": LlamaServerProvider(),
    "flm": FLMProvider(),
    "moonshine": MoonshineProvider(),
    "kokoro": KokoroProvider(),
    "comfyui": ComfyUIProvider(),
}


def get_provider(name: str) -> Provider:
    """Return the singleton Provider for ``name``.

    Raises:
        KeyError: If no provider is registered for that name. The slot
            config schema rejects unknown providers at load time, so this
            should only fire on internal misuse.
    """
    try:
        return _PROVIDERS[name]
    except KeyError as exc:
        raise KeyError(f"no provider registered for {name!r}; known: {sorted(_PROVIDERS)}") from exc


__all__ = [
    "ComfyUIProvider",
    "ContainerSpec",
    "FLMProvider",
    "KokoroProvider",
    "LlamaServerProvider",
    "MoonshineProvider",
    "Provider",
    "get_provider",
]

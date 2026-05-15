"""LlamaServerProvider — llama.cpp inference backend.

Supports Vulkan (default) and ROCm (opt-in via slot_cfg["backend"]).
Handles: chat completions, embeddings, reranking, vision.

Port target: haloai lib/providers/llama_server.py.
See PLAN.md §1 (v1 ships — llama.cpp provider) and §3 (module port plan).
"""

from __future__ import annotations

from typing import Any

from hal0.providers.base import ContainerSpec, Provider


class LlamaServerProvider(Provider):
    """Provider for llama.cpp (llama-server) backends.

    Toolbox images:
      Vulkan: ghcr.io/hal0-dev/hal0-toolbox-vulkan:v1
      ROCm:   ghcr.io/hal0-dev/hal0-toolbox-rocm:v1

    Backend is selected by slot_cfg["backend"]: "vulkan" | "rocm".
    Defaults to "vulkan" if unspecified.
    """

    name = "llama-server"

    def build_env(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> dict[str, str]:
        """Build HAL0_* env vars for a llama-server slot.

        Raises:
            NotImplementedError: Until Phase 1 port from haloai lib/providers/llama_server.py.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/providers/llama_server.py")

    def start_cmd(self, env: dict[str, str]) -> list[str]:
        """Return argv for llama-server invocation.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/providers/llama_server.py")

    async def health(self, port: int) -> dict[str, Any]:
        """Health probe: /v1/models (non-empty) + sentinel completion.

        Implements the Tier 1 fix: require non-empty /v1/models plus a
        /v1/chat/completions with max_tokens=1 before reporting ready.
        See PLAN.md §5 Tier 1.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/providers/llama_server.py")

    async def infer(self, port: int, body: dict[str, Any]) -> dict[str, Any]:
        """Passthrough inference to llama-server.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/providers/llama_server.py")

    def container_spec(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> ContainerSpec:
        """Build ContainerSpec for a llama-server slot.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/providers/llama_server.py")

    def image_ref(self, slot_cfg: dict[str, Any]) -> str:
        """Return Vulkan or ROCm toolbox image based on slot_cfg["backend"].

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/providers/llama_server.py")

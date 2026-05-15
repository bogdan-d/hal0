"""KokoroProvider — Kokoro TTS (text-to-speech) backend.

Kokoro runs CPU/Vulkan and exposes an OpenAI-compatible
/v1/audio/speech endpoint.  Wraps the Kokoro server in hal0's
container-per-slot model.

Toolbox image: ghcr.io/hal0-dev/hal0-toolbox-kokoro:v1

Port target: new hal0 provider (haloai has Kokoro as a slot but not a
typed provider class; implement from scratch following Provider ABC).
See PLAN.md §1 (v1 ships — Kokoro TTS) and §3 (new modules).
"""

from __future__ import annotations

from typing import Any

from hal0.providers.base import ContainerSpec, Provider


class KokoroProvider(Provider):
    """Provider for the Kokoro TTS backend.

    Supports:
      - POST /v1/audio/speech (OpenAI-compat TTS endpoint)
      - GET  /health
      - GET  /v1/models
    """

    name = "kokoro"

    def build_env(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> dict[str, str]:
        """Build HAL0_* env vars for a Kokoro slot.

        Raises:
            NotImplementedError: Until Phase 1 implementation.
        """
        raise NotImplementedError("Phase 1: implement KokoroProvider.build_env()")

    def start_cmd(self, env: dict[str, str]) -> list[str]:
        """Return argv for the Kokoro server invocation.

        Raises:
            NotImplementedError: Until Phase 1 implementation.
        """
        raise NotImplementedError("Phase 1: implement KokoroProvider.start_cmd()")

    async def health(self, port: int) -> dict[str, Any]:
        """Health check against GET /health on the Kokoro server.

        Raises:
            NotImplementedError: Until Phase 1 implementation.
        """
        raise NotImplementedError("Phase 1: implement KokoroProvider.health()")

    async def infer(self, port: int, body: dict[str, Any]) -> dict[str, Any]:
        """Passthrough to /v1/audio/speech.

        Raises:
            NotImplementedError: Until Phase 1 implementation.
        """
        raise NotImplementedError("Phase 1: implement KokoroProvider.infer()")

    def container_spec(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> ContainerSpec:
        """Build ContainerSpec for a Kokoro slot.

        Raises:
            NotImplementedError: Until Phase 1 implementation.
        """
        raise NotImplementedError("Phase 1: implement KokoroProvider.container_spec()")

    def image_ref(self, slot_cfg: dict[str, Any]) -> str:
        """Return the Kokoro toolbox image reference.

        Raises:
            NotImplementedError: Until Phase 1 implementation.
        """
        raise NotImplementedError("Phase 1: implement KokoroProvider.image_ref()")

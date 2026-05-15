"""MoonshineProvider — Moonshine STT (speech-to-text) backend.

Moonshine runs CPU/Vulkan and exposes an OpenAI-compatible
/v1/audio/transcriptions endpoint.  The server code lives in
haloai lib/voice/moonshine_server.py; this provider wraps it in
hal0's container-per-slot model.

Toolbox image: ghcr.io/hal0-dev/hal0-toolbox-moonshine:v1

Port target: haloai lib/voice/moonshine_server.py (new hal0 provider wrapper).
See PLAN.md §1 (v1 ships — Moonshine STT) and §3 (new modules).
"""

from __future__ import annotations

from typing import Any

from hal0.providers.base import ContainerSpec, Provider


class MoonshineProvider(Provider):
    """Provider for the Moonshine streaming STT backend.

    Supports:
      - POST /v1/audio/transcriptions (OpenAI-compat, multipart upload)
      - WS   /v1/audio/stream         (live PCM16 @ 16kHz mono → JSON events)
      - GET  /health
      - GET  /v1/models
    """

    name = "moonshine"

    def build_env(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> dict[str, str]:
        """Build HAL0_* env vars for a Moonshine slot.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/voice/moonshine_server.py")

    def start_cmd(self, env: dict[str, str]) -> list[str]:
        """Return argv for moonshine-server invocation.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/voice/moonshine_server.py")

    async def health(self, port: int) -> dict[str, Any]:
        """Health check against GET /health on the Moonshine server.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/voice/moonshine_server.py")

    async def infer(self, port: int, body: dict[str, Any]) -> dict[str, Any]:
        """Passthrough to /v1/audio/transcriptions (non-streaming path).

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/voice/moonshine_server.py")

    def container_spec(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> ContainerSpec:
        """Build ContainerSpec for a Moonshine slot.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/voice/moonshine_server.py")

    def image_ref(self, slot_cfg: dict[str, Any]) -> str:
        """Return the Moonshine toolbox image reference.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/voice/moonshine_server.py")

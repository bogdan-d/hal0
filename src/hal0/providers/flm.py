"""FLMProvider — AMD NPU inference backend.

FLM (Flexible Language Model) targets the AMD Strix Halo NPU.  Optional —
only loaded on hardware where the NPU driver is present and the FLM toolbox
image is available.

Capabilities: chat, embed, ASR multiplexed (see PLAN.md §1).
Toolbox image: ghcr.io/hal0-dev/hal0-toolbox-flm:v1

Port target: haloai lib/providers/flm.py.
See PLAN.md §1 (v1 ships — FLM provider) and §3 (module port plan).
"""

from __future__ import annotations

from typing import Any

from hal0.providers.base import ContainerSpec, Provider


class FLMProvider(Provider):
    """Provider for the AMD NPU FLM backend.

    FLM health probe must require non-empty /v1/models plus a sentinel
    completion before reporting ready (PLAN.md §5 Tier 1 fix for the
    haloai lib/slots.py:899-920 bug).
    """

    name = "flm"

    def build_env(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> dict[str, str]:
        """Build HAL0_* env vars for an FLM slot.

        Raises:
            NotImplementedError: Until Phase 1 port from haloai lib/providers/flm.py.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/providers/flm.py")

    def start_cmd(self, env: dict[str, str]) -> list[str]:
        """Return argv for FLM invocation.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/providers/flm.py")

    async def health(self, port: int) -> dict[str, Any]:
        """Health probe with Tier 1 sentinel completion fix applied.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/providers/flm.py")

    async def infer(self, port: int, body: dict[str, Any]) -> dict[str, Any]:
        """Passthrough inference to FLM.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/providers/flm.py")

    def container_spec(
        self,
        slot_cfg: dict[str, Any],
        model_info: dict[str, Any],
    ) -> ContainerSpec:
        """Build ContainerSpec for an FLM slot.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/providers/flm.py")

    def image_ref(self, slot_cfg: dict[str, Any]) -> str:
        """Return the FLM toolbox image reference.

        Raises:
            NotImplementedError: Until Phase 1 port.
        """
        raise NotImplementedError("Phase 1: port from /opt/haloai/lib/providers/flm.py")

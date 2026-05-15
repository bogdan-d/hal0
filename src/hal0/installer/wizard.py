"""First-run wizard backend.

FirstRunWizard backs the /api/install/* routes used by the FirstRun.vue
dashboard view.  It runs when /var/lib/hal0/models/ is empty.

Wizard steps:
  1. Pick a default model (curated list or custom HF URL)
  2. Confirm license
  3. Download + assign to primary slot + start the slot
  4. Done — deep link to OpenWebUI

Port target: new module (no haloai equivalent).
See PLAN.md §7 (first-run wizard) and §15 Phase 4.
"""

from __future__ import annotations

from typing import Any

#: Curated model list shown in the FirstRun wizard UI.
#: See PLAN.md §7 for the full list with sizes and licenses.
CURATED_MODELS: list[dict[str, Any]] = [
    {
        "alias": "qwen3-4b",
        "name": "Qwen3 4B",
        "hf_repo": "Qwen/Qwen3-4B-GGUF",
        "hf_filename": "qwen3-4b-q4_k_m.gguf",
        "size_gb": 4.0,
        "vram_gb": 4.0,
        "license": "Apache-2.0",
        "capabilities": ["chat", "vision"],
        "description": "General purpose, vision support, great quality/size ratio.",
    },
    {
        "alias": "llama-3.2-3b",
        "name": "Llama 3.2 3B",
        "hf_repo": "meta-llama/Llama-3.2-3B-Instruct-GGUF",
        "hf_filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "size_gb": 2.0,
        "vram_gb": 2.0,
        "license": "Llama-3",
        "capabilities": ["chat"],
        "description": "Fast, general purpose, low memory footprint.",
    },
    {
        "alias": "phi-3-mini",
        "name": "Phi-3 Mini",
        "hf_repo": "microsoft/Phi-3-mini-4k-instruct-gguf",
        "hf_filename": "Phi-3-mini-4k-instruct-q4.gguf",
        "size_gb": 2.4,
        "vram_gb": 2.4,
        "license": "MIT",
        "capabilities": ["chat"],
        "description": "Very fast, low memory, good for constrained hardware.",
    },
]


class FirstRunWizard:
    """Backend for the first-run wizard API endpoints.

    Each method corresponds to one step in the wizard flow.
    """

    async def state(self) -> dict[str, Any]:
        """Return the current wizard state (which step is active, progress, etc.).

        Raises:
            NotImplementedError: Until Phase 4.
        """
        raise NotImplementedError("Phase 4: implement FirstRunWizard.state()")

    def curated_models(self) -> list[dict[str, Any]]:
        """Return the curated model list for the wizard UI.

        This method is implemented: it returns CURATED_MODELS directly.
        """
        return list(CURATED_MODELS)

    async def pick_default(
        self,
        model_alias: str | None = None,
        hf_repo: str | None = None,
        hf_filename: str | None = None,
    ) -> dict[str, Any]:
        """Start downloading and assigning the chosen model.

        Either model_alias (from the curated list) or hf_repo + hf_filename
        must be provided.

        Returns a dict with job_id for polling progress.

        Raises:
            NotImplementedError: Until Phase 4.
        """
        raise NotImplementedError("Phase 4: implement FirstRunWizard.pick_default()")

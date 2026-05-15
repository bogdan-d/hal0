"""OpenWebUI environment file writer.

write_openwebui_env() produces /etc/hal0/openwebui.env with the variables
required to prewire OpenWebUI to the hal0 API.  Called by the installer
and (on settings changes) by the Settings API route.

Uses hal0.config.env.write_env_atomic() — the same atomic write primitive
used for slot env files (PLAN.md §5 Tier 1).

Prewired variables (PLAN.md §8):
    OPENAI_API_BASE_URLS=http://127.0.0.1:8080/v1
    WEBUI_AUTH=False
    WEBUI_NAME=hal0
    ENABLE_OPENAI_API=True
    ENABLE_OLLAMA_API=False
    DATA_DIR=/app/backend/data
    DEFAULT_LOCALE=en

See PLAN.md §8 (OpenWebUI integration) and §5 Tier 1 (atomic writes).
"""

from __future__ import annotations

from pathlib import Path

#: Default prewired variables.  Matches PLAN.md §8 exactly.
_DEFAULT_OPENWEBUI_ENV: dict[str, str] = {
    "DATA_DIR": "/app/backend/data",
    "DEFAULT_LOCALE": "en",
    "ENABLE_OLLAMA_API": "False",
    "ENABLE_OPENAI_API": "True",
    "OPENAI_API_BASE_URLS": "http://127.0.0.1:8080/v1",
    "WEBUI_AUTH": "False",
    "WEBUI_NAME": "hal0",
}


def write_openwebui_env(
    path: Path | str | None = None,
    overrides: dict[str, str] | None = None,
) -> None:
    """Write the OpenWebUI environment file atomically.

    Args:
        path:      Destination path.  Defaults to hal0.config.paths.openwebui_env()
                   (/etc/hal0/openwebui.env or $HAL0_HOME equivalent).
        overrides: Optional per-key overrides merged on top of the defaults.
                   Useful for non-standard hal0 API ports or custom WEBUI_NAME.

    Raises:
        NotImplementedError: Until Phase 2 / installer implementation.
                             The write_env_atomic primitive itself is ready.
    """
    raise NotImplementedError(
        "Phase 2: implement write_openwebui_env() — write_env_atomic() is already available"
    )

"""hal0.openwebui — OpenWebUI companion service configuration.

Writes /etc/hal0/openwebui.env with the prewired variables that configure
OpenWebUI to use the hal0 API as its backend.  Called by the installer at
install time and by the Settings API route when the hal0 API port changes.

Uses the same atomic write primitive as slot env files (hal0.config.env).

New module (no haloai equivalent).
See PLAN.md §8 (OpenWebUI integration) and §5 Tier 1 (atomic writes).

Key exports:
    write_openwebui_env — write the OpenWebUI env file atomically.
"""

from __future__ import annotations

from hal0.openwebui.env_writer import write_openwebui_env

__all__ = [
    "write_openwebui_env",
]

"""hal0.installer — First-run wizard backend and installer utilities.

Backs the /api/install/* routes consumed by the FirstRun.vue dashboard
view and the install.sh post-install setup step.

The wizard runs when /var/lib/hal0/models/ is empty, guides the user
through picking a default model, downloads it, assigns it to the primary
slot, and starts the slot.

New module (no haloai equivalent).
See PLAN.md §7 (first-run wizard) and §15 Phase 4.

Key exports:
    FirstRunWizard — wizard step controller.
"""

from __future__ import annotations

from hal0.installer.template_unit import DEFAULT_DEST, install_template_unit
from hal0.installer.wizard import FirstRunWizard

__all__ = [
    "DEFAULT_DEST",
    "FirstRunWizard",
    "install_template_unit",
]

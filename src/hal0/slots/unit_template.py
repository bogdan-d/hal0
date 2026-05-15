"""systemd unit template renderer for hal0-slot@ instances.

render_unit() produces the Override.conf content (or the full unit file,
depending on install mode) for a single slot instance.  It is called by
SlotManager.spawn() after the Provider has computed its ContainerSpec.

Port target: haloai lib/slot_unit_template.py.

NOTE: This renders the hal0-slot@.service *template* that systemd instantiates
per slot — not individual per-slot unit files.  The template is written once
at install time; per-slot overrides live in /etc/systemd/system/
hal0-slot@<name>.service.d/override.conf.

See PLAN.md §3 (module port plan) and §2 (deployment model).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hal0.config.schema import SlotConfig


def render_unit(
    slot_name: str,
    slot_cfg: SlotConfig | dict[str, Any],
    model_info: dict[str, Any],
) -> str:
    """Render the systemd unit override content for a slot instance.

    Args:
        slot_name:  The slot identifier, e.g. "primary".  Used as the
                    systemd instance name in hal0-slot@<slot_name>.service.
        slot_cfg:   SlotConfig (pydantic model) or raw dict from TOML load.
                    Must contain at minimum: port, backend, provider.
        model_info: Model metadata from the registry (id, path, size_bytes, etc.)

    Returns:
        A string containing the [Service] override block, ready to be written to
        /etc/systemd/system/hal0-slot@<slot_name>.service.d/override.conf.

    Raises:
        NotImplementedError: Until Phase 1 port from haloai lib/slot_unit_template.py.
    """
    raise NotImplementedError("Phase 1: port from /opt/haloai/lib/slot_unit_template.py")

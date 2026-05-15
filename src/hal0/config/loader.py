"""Config loaders — read and validate TOML files at startup.

All loaders return validated pydantic models.  A ValidationError at startup
means the user has a malformed config file; the error message includes the
field path (PLAN.md §5 Tier 1: "Typos in [slot] backend = vukan raise at
startup with the field path").

Port target: haloai lib/config.py (420 lines).
See PLAN.md §3 and §5 Tier 1.
"""

from __future__ import annotations

from hal0.config.schema import Hal0Config, SlotConfig


def load_hal0_config() -> Hal0Config:
    """Load and validate /etc/hal0/hal0.toml (or $HAL0_HOME equivalent).

    Uses hal0.config.paths.hal0_toml() for the path.

    Returns a validated Hal0Config.  If the file does not exist, returns
    the default config (all defaults, schema_version=1).

    Raises:
        pydantic.ValidationError: If the TOML contains invalid values.
        NotImplementedError: Until Phase 1 port.
    """
    raise NotImplementedError("Phase 1: port from /opt/haloai/lib/config.py")


def load_slot_config(slot_name: str) -> SlotConfig:
    """Load and validate /etc/hal0/slots/<slot_name>.toml.

    Uses hal0.config.paths.slots_config_dir() for the directory.

    Args:
        slot_name: e.g. "primary", "embed", "stt", "tts".

    Returns a validated SlotConfig.

    Raises:
        FileNotFoundError: If the slot TOML doesn't exist.
        pydantic.ValidationError: If the TOML contains invalid values.
        NotImplementedError: Until Phase 1 port.
    """
    raise NotImplementedError("Phase 1: port from /opt/haloai/lib/config.py")


def list_slots() -> list[str]:
    """Return all configured slot names (stems of /etc/hal0/slots/*.toml).

    Raises:
        NotImplementedError: Until Phase 1 port.
    """
    raise NotImplementedError("Phase 1: port from /opt/haloai/lib/config.py")

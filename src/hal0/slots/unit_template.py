"""systemd unit template renderer for hal0-slot@ instances.

This module is the hal0 counterpart of haloai's lib/slot_unit_template.py,
but the architecture is different:

  - haloai writes *one full unit file per slot* to
    /etc/systemd/system/haloai-<name>.service.  Adding a slot means writing
    a brand new unit.  Updating its docker flags means rewriting it.

  - hal0 ships a single *template unit* (hal0-slot@.service) at install
    time and only manages per-slot *drop-ins* and the per-slot env file.
    The drop-in lives at
        /etc/systemd/system/hal0-slot@<name>.service.d/override.conf
    and carries the slot-specific overrides.  The env file lives at
        /var/lib/hal0/slots/<name>/env
    and is loaded by the template's EnvironmentFile= directive.

This collapses the "write a full systemd unit" surface haloai re-renders on
every load() — the only file SlotManager rewrites per load is the env file
(written atomically through ``hal0.config.env.write_env_atomic``).  The
override.conf is rendered once at slot-create time and only rewritten if
the provider or backend changes.

Port target: haloai lib/slot_unit_template.py.

See PLAN.md §3 (module port plan) and §2 (deployment model).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hal0.config import paths
from hal0.config.env import write_env_atomic
from hal0.slots.state import SlotConfigError

if TYPE_CHECKING:
    from hal0.config.schema import SlotConfig


# A bare systemd variable-expansion reference like ``${HF_TOKEN}``.  When a
# provider sets a container_env value to exactly this shape, the intent is
# "let systemd substitute from EnvironmentFile" — so we must NOT quote it.
_SYSTEMD_VAR_REF = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")


# Default toolbox image per backend.  The installer materialises a concrete
# digest into hal0.toml at install-time; this map is the fallback used by
# render_override() when nothing more specific is supplied.
_DEFAULT_IMAGES: dict[str, str] = {
    "vulkan": "ghcr.io/hal0-dev/hal0-toolbox-vulkan:v1",
    "rocm": "ghcr.io/hal0-dev/hal0-toolbox-rocm:v1",
    "flm": "ghcr.io/hal0-dev/hal0-toolbox-flm:v1",
    "moonshine": "ghcr.io/hal0-dev/hal0-toolbox-moonshine:v1",
    "kokoro": "ghcr.io/hal0-dev/hal0-toolbox-kokoro:v1",
    "cpu": "ghcr.io/hal0-dev/hal0-toolbox-vulkan:v1",  # vulkan image runs CPU too
}


def _quote_env_value(value: str) -> str:
    """Quote a docker -e VALUE if it contains whitespace or $.

    Mirrors haloai's lib/slot_unit_template._quote_env_value behaviour:
    leaves a bare ``${VAR}`` reference alone so systemd expands it from the
    EnvironmentFile.
    """
    if value == "":
        return '""'
    if _SYSTEMD_VAR_REF.fullmatch(value):
        return value
    if any(ch in value for ch in (" ", "\t", "$")):
        if "'" in value:
            return '"' + value.replace('"', '\\"') + '"'
        return f"'{value}'"
    return value


def _coerce_cfg(slot_cfg: SlotConfig | dict[str, Any]) -> dict[str, Any]:
    """Return a dict view of a slot config.

    Accepts either the pydantic SlotConfig model or a raw TOML dict so this
    module stays usable both from SlotManager (typed) and from
    rendering-only utilities (dict at hand).
    """
    if hasattr(slot_cfg, "model_dump"):
        return slot_cfg.model_dump()  # type: ignore[no-any-return]
    if isinstance(slot_cfg, dict):
        return dict(slot_cfg)
    raise SlotConfigError(
        f"slot_cfg must be SlotConfig or dict, got {type(slot_cfg).__name__}",
        details={"type": type(slot_cfg).__name__},
    )


def _resolve_image(backend: str, model_info: dict[str, Any]) -> str:
    """Pick the docker image for the given backend.

    Model metadata may override (model_info["image"]) — useful for pinned
    benchmark slots.  Otherwise falls back to _DEFAULT_IMAGES.
    """
    override = model_info.get("image") or model_info.get("metadata", {}).get("image")
    if override:
        return str(override)
    return _DEFAULT_IMAGES.get(backend, _DEFAULT_IMAGES["vulkan"])


def render_override(
    slot_name: str,
    slot_cfg: SlotConfig | dict[str, Any],
    model_info: dict[str, Any] | None = None,
    *,
    image: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> str:
    """Render the per-slot drop-in for hal0-slot@<slot_name>.service.

    The drop-in overrides the template's ExecStart with the concrete docker
    image and command line, and sets the SyslogIdentifier so journald
    entries are tagged with the slot name rather than the generic
    "hal0-slot@<name>".

    Args:
        slot_name: Slot identifier — used in container name & SyslogIdentifier.
        slot_cfg:  SlotConfig pydantic model or raw dict from TOML load.
        model_info: Optional model metadata (id, path, size_bytes, image, ...).
        image:     Optional docker image override (wins over model_info["image"]).
        extra_env: Optional additional docker `-e KEY=VALUE` pairs to inject
                   (used by providers that need static env beyond what the
                   slot env file carries — e.g. HUGGINGFACE_HUB_CACHE).

    Returns:
        Override.conf text ready to be written to
        /etc/systemd/system/hal0-slot@<slot_name>.service.d/override.conf.
    """
    cfg = _coerce_cfg(slot_cfg)
    model_info = model_info or {}

    backend = cfg.get("backend", "vulkan")
    port = cfg.get("port") or cfg.get("slot", {}).get("port")
    if not port:
        raise SlotConfigError(
            f"slot {slot_name!r} config is missing a port",
            details={"slot": slot_name},
        )

    resolved_image = image or _resolve_image(backend, model_info)
    container_name = f"hal0-slot-{slot_name}"
    slot_env_file = paths.slot_data_dir(slot_name) / "env"

    docker_args: list[str] = [
        "/usr/bin/docker run --rm",
        f"--name {container_name}",
        "--network host",
        f"--env-file {slot_env_file}",
    ]
    for key, value in sorted((extra_env or {}).items()):
        docker_args.append(f"-e {key}={_quote_env_value(value)}")
    docker_args.append(resolved_image)

    exec_start = " \\\n  ".join(docker_args)

    # The drop-in MUST clear the inherited ExecStart with an empty assignment
    # before re-setting it — that is systemd's documented mechanism for
    # overriding a list-valued directive on a template unit.
    # See `systemd.unit(5)` § "Drop-in files".
    lines = [
        "# hal0 slot override — rendered by hal0.slots.unit_template.render_override",
        "# Do not edit manually; changes will be overwritten on the next slot config change.",
        "",
        "[Unit]",
        f"Description=hal0 inference slot ({slot_name})",
        "",
        "[Service]",
        f"EnvironmentFile={slot_env_file}",
        f"SyslogIdentifier=hal0-slot-{slot_name}",
        # Clear inherited ExecStart / ExecStop, then set our own.
        "ExecStart=",
        f"ExecStart={exec_start}",
        "ExecStop=",
        f"ExecStop=/usr/bin/docker stop -t 30 {container_name}",
        "ExecStopPost=-/usr/bin/docker rm -f " + container_name,
        "",
    ]
    return "\n".join(lines)


def override_path(slot_name: str) -> Path:
    """Return the on-disk path for the per-slot drop-in.

    Production: /etc/systemd/system/hal0-slot@<slot_name>.service.d/override.conf
    HAL0_HOME:  $HAL0_HOME/etc/systemd-system/hal0-slot@<slot>.service.d/override.conf

    The HAL0_HOME branch lets unit tests and the installer's dry-run mode
    exercise the rendering pipeline without root.  hal0.config.paths owns
    the HAL0_HOME resolution; we re-read it here so a test setting
    ``monkeypatch.setenv("HAL0_HOME", ...)`` flows through.
    """
    import os

    home = os.environ.get("HAL0_HOME", "").strip()
    if home:
        return (
            Path(home)
            / "etc"
            / "systemd-system"
            / f"hal0-slot@{slot_name}.service.d"
            / "override.conf"
        )
    return Path(f"/etc/systemd/system/hal0-slot@{slot_name}.service.d/override.conf")


def render_env(
    slot_name: str,
    slot_cfg: SlotConfig | dict[str, Any],
    model_info: dict[str, Any] | None = None,
    *,
    model_id_override: str | None = None,
) -> dict[str, str]:
    """Build the env dict for /var/lib/hal0/slots/<name>/env.

    These vars are consumed both by the toolbox image entrypoint (which
    expects HAL0_MODEL_PATH, HAL0_PORT, HAL0_CTX, …) and by the systemd
    unit's docker invocation (via --env-file).

    Args:
        model_id_override: When set, takes precedence over
            ``slot_cfg.model.default``.  Used by SlotManager.swap() to
            point a slot at a new model without rewriting its TOML in the
            same step.

    The actual write is performed by SlotManager.spawn() via
    write_env_atomic — keeping the rendering pure for testability.
    """
    cfg = _coerce_cfg(slot_cfg)
    model_info = model_info or {}

    port = cfg.get("port") or cfg.get("slot", {}).get("port")
    if not port:
        raise SlotConfigError(
            f"slot {slot_name!r} config is missing a port",
            details={"slot": slot_name},
        )

    model_section = cfg.get("model") or {}
    cfg_model_id = model_section.get("default", "") if isinstance(model_section, dict) else ""
    model_id = model_id_override if model_id_override is not None else cfg_model_id
    model_path = str(model_info.get("path", ""))

    env: dict[str, str] = {
        "HAL0_SLOT_NAME": slot_name,
        "HAL0_PORT": str(port),
        "HAL0_BIND_HOST": "127.0.0.1",
        "HAL0_BACKEND": str(cfg.get("backend", "vulkan")),
        "HAL0_PROVIDER": str(cfg.get("provider", "llama-server")),
        "HAL0_MODEL_ID": str(model_id),
        "HAL0_MODEL_PATH": model_path,
        "HAL0_CTX": str(
            (model_section or {}).get("context_size", 4096)
            if isinstance(model_section, dict)
            else 4096
        ),
        "HAL0_N_GPU_LAYERS": str(
            (model_section or {}).get("n_gpu_layers", -1) if isinstance(model_section, dict) else -1
        ),
        "HAL0_WORKERS": str(cfg.get("workers", 1)),
    }
    # Provider-specific verbatim extras.
    extra = cfg.get("extra") or {}
    if isinstance(extra, dict):
        for k, v in extra.items():
            # systemd EnvironmentFile keys must be UPPER_SNAKE_CASE.
            env_key = f"HAL0_EXTRA_{str(k).upper()}"
            env[env_key] = str(v)
    return env


def write_slot_env(
    slot_name: str,
    slot_cfg: SlotConfig | dict[str, Any],
    model_info: dict[str, Any] | None = None,
    *,
    target_path: Path | None = None,
    model_id_override: str | None = None,
) -> Path:
    """Render and atomically write the slot env file.

    TIER1: Uses ``hal0.config.env.write_env_atomic`` — tmpfile + os.replace.
    A failed write leaves the prior env intact.  Replaces haloai
    lib/slots.py:551-622 (non-atomic env write bug).
    """
    env = render_env(slot_name, slot_cfg, model_info, model_id_override=model_id_override)
    path = target_path or (paths.slot_data_dir(slot_name) / "env")
    write_env_atomic(path, env)
    return path


# Backwards-compatible alias matching the old haloai signature.  Provider
# code in the rest of the hal0 tree should prefer ``render_override``.
def render_unit(
    slot_name: str,
    slot_cfg: SlotConfig | dict[str, Any],
    model_info: dict[str, Any],
) -> str:
    """Compatibility shim — delegates to render_override.

    NOTE: hal0's template-unit pattern does NOT render a full unit per slot;
    callers wanting the drop-in should use ``render_override`` directly.
    This shim exists so the original ``manager.create_unit()`` call sites
    can be ported without immediate renaming.
    """
    return render_override(slot_name, slot_cfg, model_info)


__all__ = [
    "override_path",
    "render_env",
    "render_override",
    "render_unit",
    "write_slot_env",
]

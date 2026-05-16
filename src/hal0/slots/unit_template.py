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

The docker-run line itself is built by ``Provider.render_systemd_override``
from the provider's :class:`hal0.providers.ContainerSpec`.  This module is
the orchestration seam: SlotManager calls ``render_override``, which
looks up the provider and delegates.  Keeping the lookup here (rather
than in SlotManager) preserves the architectural rule that SlotManager
is *pure systemd* — it never imports providers directly.

Port target: haloai lib/slot_unit_template.py.

See PLAN.md §3 (module port plan) and §2 (deployment model).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from hal0.config import paths
from hal0.config.env import write_env_atomic
from hal0.slots.state import SlotConfigError

if TYPE_CHECKING:
    from hal0.config.schema import SlotConfig


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


def render_override(
    slot_name: str,
    slot_cfg: SlotConfig | dict[str, Any],
    model_info: dict[str, Any] | None = None,
    *,
    image: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> str:
    """Render the per-slot drop-in for hal0-slot@<slot_name>.service.

    Delegates to ``Provider.render_systemd_override`` so the rendered
    docker line stays consistent with the Provider's :class:`ContainerSpec`
    (devices, group_add, security_opt, mounts, command, image).  The
    Provider base class owns the systemd quoting and drop-in layout;
    concrete Providers contribute the spec via ``container_spec()``.

    Args:
        slot_name: Slot identifier — used in container name & SyslogIdentifier.
        slot_cfg:  SlotConfig pydantic model or raw dict from TOML load.
        model_info: Optional model metadata (id, path, size_bytes, image, ...).
        image:     Optional docker image override (wins over slot_cfg["image"]
                   and ``HAL0_TOOLBOX_IMAGE_<BACKEND>``).  Injected into
                   slot_cfg so the Provider's ``image_ref()`` picks it up
                   through its normal resolution path.
        extra_env: Optional additional docker ``-e KEY=VALUE`` pairs to
                   inject.  Merged into ContainerSpec.env so the rendered
                   docker line includes them.

    Returns:
        Override.conf text ready to be written to
        /etc/systemd/system/hal0-slot@<slot_name>.service.d/override.conf.
    """
    # Local import avoids a load-time cycle: providers/__init__.py
    # eventually pulls hal0.api.middleware, which the SlotManager-side
    # import graph also touches.  Keeping this lazy makes the renderer
    # safe to import from anywhere.
    from hal0.providers import get_provider

    cfg = _coerce_cfg(slot_cfg)
    model_info = dict(model_info or {})

    port = cfg.get("port") or cfg.get("slot", {}).get("port")
    if not port:
        raise SlotConfigError(
            f"slot {slot_name!r} config is missing a port",
            details={"slot": slot_name},
        )

    # The legacy ``image=`` parameter is funnelled into the slot config
    # so Provider.image_ref() picks it up through its normal resolution
    # path (slot_cfg["image"] → env var → default map).
    if image:
        cfg = {**cfg, "image": image}

    provider_name = cfg.get("provider", "llama-server")
    try:
        provider = get_provider(provider_name)
    except KeyError as exc:
        raise SlotConfigError(
            f"slot {slot_name!r} references unknown provider {provider_name!r}",
            details={"slot": slot_name, "provider": provider_name},
        ) from exc

    slot_env_file = paths.slot_data_dir(slot_name) / "env"

    if not extra_env:
        return provider.render_systemd_override(
            slot_name,
            cfg,
            model_info,
            env_file_path=slot_env_file,
        )

    # extra_env path: render with a spec whose env has been merged.
    # Provider.render_systemd_override rebuilds the spec internally, so
    # for this case we build the spec ourselves, mutate it, then call
    # the base-class renderer directly.
    from dataclasses import replace

    spec = provider.container_spec(cfg, model_info)
    merged_spec = replace(spec, env={**spec.env, **extra_env})
    return _render_from_spec(
        slot_name,
        merged_spec,
        provider_name,
        env_file_path=slot_env_file,
    )


def _render_from_spec(
    slot_name: str,
    spec: Any,  # ContainerSpec; ``Any`` to avoid a top-level import cycle
    provider_name: str,
    *,
    env_file_path: Path,
    container_runtime: str = "/usr/bin/docker",
) -> str:
    """Render a drop-in directly from an already-built ContainerSpec.

    Mirrors the default :meth:`Provider.render_systemd_override`
    implementation but skips the ``container_spec`` rebuild so callers
    can mutate the spec (e.g. inject ``extra_env``) before rendering.

    Kept in this module rather than on the Provider base class so the
    Provider contract stays minimal — Providers contribute *specs*, the
    renderer owns *systemd drop-in shape*.
    """
    # Re-use the Provider base class quoting helper to stay consistent.
    from hal0.providers.base import _quote_for_systemd

    container_name = f"hal0-slot-{slot_name}"

    argv: list[str] = [
        f"{container_runtime} run --rm",
        f"--name {container_name}",
        f"--env-file {env_file_path}",
    ]
    if spec.network_mode:
        argv.append(f"--network {spec.network_mode}")
    for host_path, container_path in spec.mounts:
        argv.append(f"-v {_quote_for_systemd(host_path)}:{_quote_for_systemd(container_path)}")
    for device in spec.devices:
        argv.append(f"--device {_quote_for_systemd(device)}")
    for group in spec.group_add:
        argv.append(f"--group-add {_quote_for_systemd(str(group))}")
    for cap in spec.cap_add:
        argv.append(f"--cap-add {_quote_for_systemd(cap)}")
    for opt in spec.security_opt:
        argv.append(f"--security-opt {_quote_for_systemd(opt)}")
    for key, value in sorted(spec.env.items()):
        argv.append(f"-e {key}={_quote_for_systemd(value)}")
    argv.extend(spec.extra_args)
    argv.append(_quote_for_systemd(spec.image))
    for arg in spec.command:
        argv.append(_quote_for_systemd(arg))

    exec_start = " \\\n  ".join(argv)
    lines = [
        f"# hal0 slot override — rendered by hal0.slots.unit_template ({provider_name})",
        "# Do not edit manually; changes will be overwritten on the next slot config change.",
        "",
        "[Unit]",
        f"Description=hal0 inference slot ({slot_name})",
        "",
        "[Service]",
        f"EnvironmentFile={env_file_path}",
        f"SyslogIdentifier=hal0-slot-{slot_name}",
        "ExecStart=",
        f"ExecStart={exec_start}",
        "ExecStop=",
        f"ExecStop={container_runtime} stop -t 30 {container_name}",
        f"ExecStopPost=-{container_runtime} rm -f {container_name}",
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

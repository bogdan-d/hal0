"""Shared helpers for GPU device + group exposure to provider containers.

Lives here so each provider (llama-server, moonshine, kokoro, flm, …) gets
the same numeric-GID treatment for ``docker run --group-add``: the toolbox
images ship with a stock ``ubuntu:24.04`` ``/etc/group`` that has no
``render``/``video`` entries, so passing the names fails fast inside the
container ("unable to find group ..."). The kernel only checks integers
when gating access to ``/dev/dri/renderD128`` etc., so resolve to host
GIDs once and pass them through.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


def resolve_gpu_group_ids() -> list[int]:
    """Return numeric GIDs for the host's GPU access groups.

    Falls back to the Linux convention (render=993, video=44) on systems
    without ``grp`` (Windows hosts). Skips groups that don't exist on the
    host rather than guessing — passing a non-existent GID to docker is a
    silent permissions hole.
    """
    gids: list[int] = []
    try:
        import grp

        for name, _fallback in (("render", 993), ("video", 44)):
            try:
                gids.append(grp.getgrnam(name).gr_gid)
            except KeyError:
                log.debug("provider.gpu_group_missing", group=name)
    except ImportError:
        gids = [993, 44]
    return gids


__all__ = ["resolve_gpu_group_ids"]

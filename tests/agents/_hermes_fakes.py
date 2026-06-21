"""Shared test fakes for the hermes_provision config-set redesign.

``apply_hermes_config_cli`` mirrors ``hermes config set`` / ``config migrate``
against a real ``$HERMES_HOME/config.yaml`` (including hermes's value coercion),
so phase + pipeline tests can assert on the resulting file exactly as the live
CLI would leave it — without a real hermes binary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class _Completed:
    returncode = 0
    stdout = ""
    stderr = ""


def _coerce(value: str) -> Any:
    """Mirror ``hermes config set`` value coercion (verified on 0.17)."""
    if value in ("true", "false"):
        return value == "true"
    try:
        return int(value)
    except ValueError:
        return value


def _set_dotted(data: dict[str, Any], dotted: str, value: Any) -> None:
    cur = data
    parts = dotted.split(".")
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def apply_hermes_config_cli(argv: list[str], env: dict[str, str] | None) -> bool:
    """Apply a ``hermes config set/migrate`` argv to ``$HERMES_HOME/config.yaml``.

    Returns True if it handled the argv (a config verb), False otherwise so a
    caller can fall through to other interception or a real subprocess.
    """
    import yaml

    home = (env or {}).get("HERMES_HOME")
    cfg = Path(home) / "config.yaml" if home else None
    verb = argv[1:3]
    if verb == ["config", "migrate"]:
        if cfg is not None and not cfg.exists():
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text("{}\n")
        return True
    if verb == ["config", "set"] and cfg is not None:
        data = (yaml.safe_load(cfg.read_text()) if cfg.exists() else None) or {}
        _set_dotted(data, argv[3], _coerce(argv[4]))
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(yaml.safe_dump(data, sort_keys=False))
        return True
    return False


def fake_hermes_run(record: list[list[str]] | None = None):
    """A stand-in for ``subprocess.run`` that applies hermes config verbs."""

    def run(argv: Any, *_a: Any, env: Any = None, **_kw: Any) -> Any:
        argv = list(argv)
        if record is not None:
            record.append(argv)
        apply_hermes_config_cli(argv, env)
        return _Completed()

    return run

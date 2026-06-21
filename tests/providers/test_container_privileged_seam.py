"""Tests for the privileged seam (D hardened-perms).

When hal0-api runs as the unprivileged ``hal0`` user (euid != 0) the container
provider must route the two root operations — writing the per-slot unit +
daemon-reload, and running systemctl on hal0-slot@<name> — through
``sudo -n <_HAL0_SLOTCTL> <verb> <slot>`` instead of touching
/etc/systemd/system or calling systemctl directly.

When running as root (euid == 0) the behavior is unchanged: the unit file is
written with ``write_text`` and the systemctl verbs go through ``_run``. These
tests pin both branches so the seam stays a no-op for root.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from hal0.providers import container as container_mod
from hal0.providers.container import ContainerProvider

_STUB_SLOTCTL = "/stub/hal0-slotctl"


def _ok() -> MagicMock:
    m = MagicMock()
    m.returncode = 0
    return m


# ── non-root (euid != 0): everything routes through sudo hal0-slotctl ────────


def test_load_path_uses_sudo_slotctl_when_unprivileged(tmp_path: Path) -> None:
    """Load writes the unit + restarts via the seam, never touching disk/_run."""
    slot_name = "chat"
    provider = ContainerProvider()
    unit_path = tmp_path / f"hal0-slot@{slot_name}.service"
    unit_text = "[Unit]\nDescription=test\n"

    priv_calls: list[tuple[list[str], str | None]] = []

    def fake_subprocess_run(argv, *, input=None, **kwargs):
        priv_calls.append((list(argv), input))
        return _ok()

    run_calls: list[list[str]] = []

    def fake_run(*args: str, check: bool = True) -> MagicMock:
        run_calls.append(list(args))
        return _ok()

    with (
        patch.object(container_mod.os, "geteuid", return_value=1000),
        patch.object(container_mod, "_HAL0_SLOTCTL", _STUB_SLOTCTL),
        patch.object(container_mod.subprocess, "run", side_effect=fake_subprocess_run),
        patch.object(provider, "_run", side_effect=fake_run),
        patch.object(provider, "_unit_path", return_value=unit_path),
    ):
        provider._write_and_start_unit(slot_name, unit_text)

    # No direct systemctl via _run, and the unit file was NOT written to disk.
    assert run_calls == [], f"unprivileged path must not use _run directly: {run_calls}"
    assert not unit_path.exists(), "unprivileged path must not write the unit file directly"

    cmds = [argv for argv, _ in priv_calls]
    # write-unit carries the unit text on stdin.
    write = [(argv, stdin) for argv, stdin in priv_calls if "write-unit" in argv]
    assert write, f"expected a write-unit seam call; got {cmds}"
    write_argv, write_stdin = write[0]
    assert write_argv == ["sudo", "-n", _STUB_SLOTCTL, "write-unit", slot_name]
    assert write_stdin == unit_text, "unit text must be piped to write-unit"

    # enable + restart routed through the seam with the bare slot name.
    assert ["sudo", "-n", _STUB_SLOTCTL, "enable", slot_name] in cmds
    assert ["sudo", "-n", _STUB_SLOTCTL, "restart", slot_name] in cmds


def test_unload_path_uses_remove_unit_when_unprivileged(tmp_path: Path) -> None:
    """Teardown stops/disables + remove-units via the seam, never _run/unlink."""
    slot_name = "chat"
    provider = ContainerProvider()
    unit_path = tmp_path / f"hal0-slot@{slot_name}.service"
    unit_path.write_text("[Unit]\nDescription=stale\n")

    priv_calls: list[list[str]] = []

    def fake_subprocess_run(argv, *, input=None, **kwargs):
        priv_calls.append(list(argv))
        return _ok()

    run_calls: list[list[str]] = []

    def fake_run(*args: str, check: bool = True) -> MagicMock:
        run_calls.append(list(args))
        return _ok()

    with (
        patch.object(container_mod.os, "geteuid", return_value=1000),
        patch.object(container_mod, "_HAL0_SLOTCTL", _STUB_SLOTCTL),
        patch.object(container_mod.subprocess, "run", side_effect=fake_subprocess_run),
        patch.object(provider, "_run", side_effect=fake_run),
        patch.object(provider, "_unit_path", return_value=unit_path),
    ):
        provider.unload_sync({"name": slot_name})

    assert run_calls == [], f"unprivileged teardown must not use _run directly: {run_calls}"
    # remove-unit owns the file removal; the provider must not unlink it itself.
    assert ["sudo", "-n", _STUB_SLOTCTL, "stop", slot_name] in priv_calls
    assert ["sudo", "-n", _STUB_SLOTCTL, "disable", slot_name] in priv_calls
    assert ["sudo", "-n", _STUB_SLOTCTL, "remove-unit", slot_name] in priv_calls


# ── root (euid == 0): unchanged direct path ──────────────────────────────────


def test_load_path_direct_when_root(tmp_path: Path) -> None:
    """As root the unit is written with write_text and systemctl goes via _run."""
    slot_name = "chat"
    provider = ContainerProvider()
    unit_path = tmp_path / f"hal0-slot@{slot_name}.service"
    unit_text = "[Unit]\nDescription=test\n"

    run_calls: list[list[str]] = []

    def fake_run(*args: str, check: bool = True) -> MagicMock:
        run_calls.append(list(args))
        return _ok()

    # If the seam were ever used as root this would fire and fail the test.
    def boom_subprocess_run(*a, **k):
        raise AssertionError("root path must not invoke subprocess.run (the seam)")

    with (
        patch.object(container_mod.os, "geteuid", return_value=0),
        patch.object(container_mod.subprocess, "run", side_effect=boom_subprocess_run),
        patch.object(provider, "_run", side_effect=fake_run),
        patch.object(provider, "_unit_path", return_value=unit_path),
    ):
        provider._write_and_start_unit(slot_name, unit_text)

    # Unit file written directly to disk.
    assert unit_path.read_text() == unit_text
    cmds = [" ".join(c) for c in run_calls]
    assert any("daemon-reload" in c for c in cmds), cmds
    assert any(c == f"systemctl restart {provider._unit_name(slot_name)}" for c in cmds), cmds


def test_unload_path_direct_when_root(tmp_path: Path) -> None:
    """As root teardown unlinks the unit and uses _run for systemctl."""
    slot_name = "chat"
    provider = ContainerProvider()
    unit_path = tmp_path / f"hal0-slot@{slot_name}.service"
    unit_path.write_text("[Unit]\nDescription=stale\n")

    run_calls: list[list[str]] = []

    def fake_run(*args: str, check: bool = True) -> MagicMock:
        run_calls.append(list(args))
        return _ok()

    def boom_subprocess_run(*a, **k):
        raise AssertionError("root teardown must not invoke subprocess.run (the seam)")

    with (
        patch.object(container_mod.os, "geteuid", return_value=0),
        patch.object(container_mod.subprocess, "run", side_effect=boom_subprocess_run),
        patch.object(provider, "_run", side_effect=fake_run),
        patch.object(provider, "_unit_path", return_value=unit_path),
    ):
        provider.unload_sync({"name": slot_name})

    assert not unit_path.exists(), "root teardown should unlink the unit file directly"
    cmds = [" ".join(c) for c in run_calls]
    assert any("systemctl stop" in c for c in cmds), cmds
    assert any("daemon-reload" in c for c in cmds), cmds

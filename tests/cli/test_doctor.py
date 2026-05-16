"""Tests for the ``hal0 doctor`` CLI subcommand.

The command shells out to ``installer/lib/preflight.sh``, so we exercise
it with the script set to a known shape via the ``HAL0_PREFLIGHT_SH``
env override. ``capfd`` captures the subprocess's file-descriptor-level
output (CliRunner's StringIO can't see past subprocess.run).

Skipped on non-Linux platforms — the real preflight script depends on
``systemctl`` / ``df`` / ``ss`` which only mean something on Linux.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest
import typer

from hal0.cli.doctor_commands import _locate_preflight, doctor

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="preflight.sh is Linux-only")


def _make_stub(tmp_path: Path, body: str) -> Path:
    """Write `body` as an executable bash stub and return its path."""
    stub = tmp_path / "preflight.sh"
    stub.write_text("#!/usr/bin/env bash\n" + body)
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def _exit_code(exc: pytest.ExceptionInfo[typer.Exit] | typer.Exit) -> int:
    """Pull the exit code off a typer.Exit (raised by the doctor command)."""
    err = exc.value if isinstance(exc, pytest.ExceptionInfo) else exc
    code = err.exit_code
    return int(code) if code is not None else 0


def test_doctor_success_propagates_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """A passing preflight script exits 0 and stdout is non-empty."""
    stub = _make_stub(tmp_path, "printf 'all good\\n'\nexit 0\n")
    monkeypatch.setenv("HAL0_PREFLIGHT_SH", str(stub))

    with pytest.raises(typer.Exit) as exc:
        doctor(plain=False, ports=None)

    assert _exit_code(exc) == 0
    captured = capfd.readouterr()
    assert "all good" in captured.out


def test_doctor_failure_propagates_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """A failing preflight script (rc=1) surfaces as a non-zero hal0 doctor exit."""
    stub = _make_stub(tmp_path, "printf 'disk: only 7 GB free\\n'\nexit 1\n")
    monkeypatch.setenv("HAL0_PREFLIGHT_SH", str(stub))

    with pytest.raises(typer.Exit) as exc:
        doctor(plain=False, ports=None)

    assert _exit_code(exc) == 1
    captured = capfd.readouterr()
    assert "disk" in captured.out


def test_doctor_missing_script_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the script can't be found we exit 2 with a helpful message."""
    monkeypatch.setenv("HAL0_PREFLIGHT_SH", "/definitely/not/a/real/path.sh")

    with pytest.raises(typer.Exit) as exc:
        doctor(plain=False, ports=None)

    assert _exit_code(exc) == 2


def test_doctor_forwards_plain_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """``--plain`` sets HAL0_PLAIN=1 in the child shell."""
    stub = _make_stub(
        tmp_path,
        'printf "HAL0_PLAIN=%s\\n" "${HAL0_PLAIN:-unset}"\nexit 0\n',
    )
    monkeypatch.setenv("HAL0_PREFLIGHT_SH", str(stub))

    with pytest.raises(typer.Exit) as exc:
        doctor(plain=True, ports=None)

    assert _exit_code(exc) == 0
    captured = capfd.readouterr()
    assert "HAL0_PLAIN=1" in captured.out


def test_doctor_forwards_ports_option(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """``--ports "1 2 3"`` propagates as HAL0_DOCTOR_PORTS."""
    stub = _make_stub(
        tmp_path,
        'printf "PORTS=%s\\n" "${HAL0_DOCTOR_PORTS:-unset}"\nexit 0\n',
    )
    monkeypatch.setenv("HAL0_PREFLIGHT_SH", str(stub))

    with pytest.raises(typer.Exit) as exc:
        doctor(plain=False, ports="9090 9091")

    assert _exit_code(exc) == 0
    captured = capfd.readouterr()
    assert "PORTS=9090 9091" in captured.out


def test_locate_preflight_finds_repo_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In an editable install the locator finds installer/lib/preflight.sh."""
    monkeypatch.delenv("HAL0_PREFLIGHT_SH", raising=False)
    found = _locate_preflight()
    assert found is not None, "expected to locate installer/lib/preflight.sh"
    assert found.name == "preflight.sh"
    assert os.access(found, os.R_OK)


def test_locate_preflight_honors_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HAL0_PREFLIGHT_SH wins over the package-relative lookup."""
    custom = tmp_path / "custom.sh"
    custom.write_text("#!/usr/bin/env bash\nexit 0\n")
    monkeypatch.setenv("HAL0_PREFLIGHT_SH", str(custom))

    found = _locate_preflight()
    assert found == custom


def test_locate_preflight_missing_override_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bogus HAL0_PREFLIGHT_SH path resolves to None, not a falsy default."""
    monkeypatch.setenv("HAL0_PREFLIGHT_SH", "/no/such/file.sh")
    assert _locate_preflight() is None

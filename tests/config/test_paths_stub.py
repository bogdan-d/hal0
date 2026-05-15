"""Smoke tests for hal0.config.paths.

Verifies the FHS-aware path resolver functions behave correctly under
both default (FHS) and HAL0_HOME-overridden conditions.
"""

from __future__ import annotations

from pathlib import Path

from hal0.config import paths


def test_paths_module_exports_expected_functions() -> None:
    """All documented path resolvers exist and are callable."""
    expected = (
        "usr_lib",
        "etc",
        "var_lib",
        "var_log",
        "slots_config_dir",
        "registry_dir",
        "models_dir",
        "openwebui_data_dir",
        "hardware_json",
        "openwebui_env",
        "hal0_toml",
    )
    for name in expected:
        fn = getattr(paths, name, None)
        assert callable(fn), f"paths.{name} is not callable"


def test_paths_return_pathlib_paths() -> None:
    for name in ("usr_lib", "etc", "var_lib", "var_log"):
        result = getattr(paths, name)()
        assert isinstance(result, Path), f"paths.{name}() returned {type(result)}"


def test_hal0_home_override(tmp_hal0_home: str) -> None:
    """When HAL0_HOME is set, all roots live under it."""
    home = Path(tmp_hal0_home)
    assert str(home) in str(paths.etc()), "etc() ignored HAL0_HOME"
    assert str(home) in str(paths.var_lib()), "var_lib() ignored HAL0_HOME"
    assert str(home) in str(paths.usr_lib()), "usr_lib() ignored HAL0_HOME"

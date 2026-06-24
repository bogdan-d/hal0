"""Tests: resolved_argv_detail_for_slot — the provenance-annotated resolution.

Backs the dashboard's "resolved command" drawer and GET /api/slots/{name}/resolved:
the deduped argv plus, per flag, which segment (base / profile / extra_args) set
its final value and how many duplicates were collapsed.
"""

from __future__ import annotations

from unittest.mock import patch

from hal0.config.schema import ProfileConfig
from hal0.providers.container import resolved_argv_detail_for_slot


def _profile() -> ProfileConfig:
    return ProfileConfig(image="img:1", flags="-b 512 --jinja", mtp=False)


def test_detail_dedups_and_attributes_provenance() -> None:
    cfg = {
        "profile": "p",
        "port": 8101,
        "model": {"default": "m", "context_size": 4096},
        "server": {"extra_args": "-b 8192"},  # overrides the profile's -b
    }
    with patch("hal0.providers.container._resolve_profile", return_value=_profile()):
        detail = resolved_argv_detail_for_slot(cfg)

    assert detail is not None
    assert detail["argv"][0] == "img:1"
    # -b deduped to one occurrence, extra_args value wins
    assert detail["argv"].count("-b") == 1
    assert detail["removed"] == 1

    prov = {p["flag"]: p for p in detail["provenance"]}
    assert prov["-b"]["source"] == "extra_args"
    assert prov["-b"]["value"] == "8192"
    assert prov["--jinja"]["source"] == "profile"
    assert prov["--jinja"]["value"] is None
    # base-segment structural flags are credited to "base"
    assert prov["--model"]["source"] == "base"
    assert prov["--model"]["value"] == "m"
    assert prov["--ctx-size"]["value"] == "4096"


def test_detail_none_without_profile() -> None:
    assert resolved_argv_detail_for_slot({"model": {"default": "m"}}) is None

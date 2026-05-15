"""Unit tests for hal0.upstreams.integrations.

Hygiene checks on the static provider catalog:
  - every entry parses (validate_catalog() returns no errors)
  - every entry has a base_url unless category == 'custom'
  - no duplicate names
  - id field matches the dict key
  - capabilities list is a subset of the known set
  - get_catalog_entry returns a deep copy (mutation doesn't leak back)
"""

from __future__ import annotations

from hal0.upstreams import integrations


def test_validate_catalog_no_problems() -> None:
    problems = integrations.validate_catalog()
    assert problems == [], f"catalog has problems: {problems}"


def test_no_duplicate_names() -> None:
    names = [entry["name"] for entry in integrations.get_catalog().values()]
    assert len(names) == len(set(names))


def test_ids_match_keys() -> None:
    for cid, entry in integrations.get_catalog().items():
        assert entry["id"] == cid


def test_base_url_present_except_custom() -> None:
    for cid, entry in integrations.get_catalog().items():
        if entry["category"] != "custom":
            assert entry["base_url"], f"{cid}: base_url is required for non-custom"


def test_every_entry_has_required_fields() -> None:
    required = {
        "id",
        "name",
        "base_url",
        "auth",
        "models_path",
        "default_models",
        "default_model",
        "capabilities",
        "category",
        "notes",
    }
    for cid, entry in integrations.get_catalog().items():
        missing = required - set(entry.keys())
        assert not missing, f"{cid}: missing fields {missing}"


def test_known_providers_present() -> None:
    """The four providers called out in PLAN §1 (OpenRouter, Anthropic, OpenAI, Ollama)
    must all be in the catalog. 'custom' is the escape hatch."""
    ids = set(integrations.list_catalog_ids())
    for required in ("openrouter", "anthropic", "openai", "ollama", "custom"):
        assert required in ids, f"catalog missing {required!r}"


def test_get_catalog_entry_returns_copy() -> None:
    """Mutating a returned entry must not poison the static catalog."""
    e = integrations.get_catalog_entry("openai")
    assert e is not None
    e["base_url"] = "https://corrupted.example.com"
    fresh = integrations.get_catalog_entry("openai")
    assert fresh is not None
    assert fresh["base_url"] == "https://api.openai.com/v1"


def test_get_catalog_returns_copy() -> None:
    cat = integrations.get_catalog()
    cat["openai"]["base_url"] = "https://corrupted.example.com"
    fresh = integrations.get_catalog()
    assert fresh["openai"]["base_url"] == "https://api.openai.com/v1"


def test_get_catalog_entry_unknown() -> None:
    assert integrations.get_catalog_entry("does-not-exist") is None


def test_capabilities_subset_of_known() -> None:
    allowed = {"chat", "embed", "rerank", "stt", "tts", "vision", "tools"}
    for cid, entry in integrations.get_catalog().items():
        for cap in entry["capabilities"]:
            assert cap in allowed, f"{cid}: unknown capability {cap!r}"


def test_auth_styles_are_known() -> None:
    allowed = {"bearer", "anthropic", "google_query", "header", "none"}
    for cid, entry in integrations.get_catalog().items():
        assert entry["auth"] in allowed, f"{cid}: bad auth {entry['auth']!r}"

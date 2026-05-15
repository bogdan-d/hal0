"""Catalog of well-known external AI providers.

_CATALOG is the built-in provider template registry.  It is never mutated
at runtime; user configuration lives in /etc/hal0/upstreams.toml.

Auth styles:
    "bearer"          → Authorization: Bearer <key>              (most providers)
    "anthropic"       → x-api-key: <key>  +  anthropic-version  (Anthropic only)
    "google_query"    → ?key=<key> on the URL                    (Google AI Studio)
    "header"          → custom header_name: <key>                ("custom" only)
    "none"            → no auth header                           ("custom" only)

API keys are NEVER written to TOML.  They live in the slot env file managed
by hal0.config.env.write_env_atomic; the key's env var name is stored in
the TOML as auth_value_env.

Port target: haloai lib/integrations.py.
See PLAN.md §3 (module port plan — "provider catalog").
"""

from __future__ import annotations

from typing import Any

# ── Catalog ────────────────────────────────────────────────────────────────────
#
# Each entry is a dict that can be used to construct an Upstream from
# upstreams.registry.  Keys:
#   id             — unique catalog id (used as TOML catalog_id reference)
#   name           — display name
#   base_url       — default base URL
#   auth           — auth style (see docstring above)
#   models_path    — path for model listing relative to base_url; "" = unsupported
#   default_models — curated list of model ids to seed UI suggestions
#   docs_url       — link to API key / docs page
#   category       — "cloud" | "local" | "custom"
#   notes          — short description shown in the Providers UI

_CATALOG: dict[str, dict[str, Any]] = {
    # ── Cloud providers ─────────────────────────────────────────────────────────
    "openai": {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "auth": "bearer",
        "models_path": "/models",
        "default_models": ["gpt-4o", "gpt-4o-mini", "o1-mini"],
        "docs_url": "https://platform.openai.com/api-keys",
        "category": "cloud",
        "notes": "Official OpenAI API.",
    },
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "auth": "anthropic",
        "models_path": "/models",
        "default_models": [
            "claude-opus-4-7-20251101",
            "claude-sonnet-4-6-20251101",
            "claude-haiku-4-5-20251001",
        ],
        "docs_url": "https://console.anthropic.com/settings/keys",
        "category": "cloud",
        "notes": (
            "Official Anthropic API. Native /v1/messages protocol. "
            "For OpenAI-shaped /v1/chat/completions with Claude models, "
            "route via a compatible proxy."
        ),
    },
    "openrouter": {
        "id": "openrouter",
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "auth": "bearer",
        "models_path": "/models",
        "default_models": [
            "openai/gpt-4o",
            "anthropic/claude-opus-4-7",
            "meta-llama/llama-3.1-70b-instruct",
        ],
        "docs_url": "https://openrouter.ai/keys",
        "category": "cloud",
        "notes": "OpenRouter aggregates 200+ models behind one OpenAI-compatible endpoint.",
    },
    "google_ai_studio": {
        "id": "google_ai_studio",
        "name": "Google AI Studio",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "auth": "google_query",
        "models_path": "/models",
        "default_models": ["gemini-2.0-flash", "gemini-1.5-pro"],
        "docs_url": "https://aistudio.google.com/app/apikey",
        "category": "cloud",
        "notes": "Google Gemini via the OpenAI-compatible REST layer.",
    },
    # ── Local / self-hosted ──────────────────────────────────────────────────────
    "ollama": {
        "id": "ollama",
        "name": "Ollama",
        "base_url": "http://localhost:11434/v1",
        "auth": "none",
        "models_path": "/models",
        "default_models": [],
        "docs_url": "https://github.com/ollama/ollama",
        "category": "local",
        "notes": "Local Ollama server. Leave key blank if running unauthenticated.",
    },
    # ── Custom (escape hatch) ────────────────────────────────────────────────────
    "custom": {
        "id": "custom",
        "name": "Custom OpenAI-compatible",
        "base_url": "",
        "auth": "bearer",
        "models_path": "/models",
        "default_models": [],
        "docs_url": "",
        "category": "custom",
        "notes": "Any OpenAI-compatible endpoint.",
    },
}


def get_catalog() -> dict[str, dict[str, Any]]:
    """Return all catalog entries (read-only copy)."""
    return dict(_CATALOG)


def get_catalog_entry(catalog_id: str) -> dict[str, Any] | None:
    """Return a single catalog entry by id, or None if not found."""
    return _CATALOG.get(catalog_id)


def list_catalog_ids() -> list[str]:
    """Return all known catalog ids."""
    return list(_CATALOG.keys())

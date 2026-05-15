"""hal0.auth — bearer-token + Caddy-edge authentication.

Two auth surfaces coexist:

  1. **Bearer tokens** (programmatic). Validated by the FastAPI dependency
     :func:`hal0.api.middleware.auth.require_token`. Tokens live in
     ``/etc/hal0/tokens.toml`` (argon2id-hashed); created/listed/revoked
     via ``/api/auth/tokens`` and the Settings UI panel.

  2. **Caddy basic_auth** (browser). Caddy terminates HTTPS, runs
     basic_auth at the edge, then forwards the authenticated identity as
     ``X-Forwarded-Email``. The hal0 API trusts the header *only* when no
     Bearer token was presented (Bearer always wins) — see
     :mod:`hal0.api.middleware.auth` for the precedence logic.

The whole stack is gated by ``HAL0_AUTH_ENABLED``: when the env var is
absent or ``"0"``/``"false"`` the dependency is a no-op pass-through. The
``--auth=basic`` installer flag flips this to ``"1"`` after rendering the
Caddyfile and starting ``hal0-caddy.service``.

There is intentionally no login page inside hal0 itself — Caddy owns the
browser authentication boundary. A future swap to OIDC/SAML/OAuth is a
Caddy module change, not a hal0 change.
"""

from __future__ import annotations

from hal0.auth.passwords import hash_password, verify_password
from hal0.auth.tokens import (
    Token,
    TokenStore,
    auth_enabled,
    default_token_store_path,
)

__all__ = [
    "Token",
    "TokenStore",
    "auth_enabled",
    "default_token_store_path",
    "hash_password",
    "verify_password",
]

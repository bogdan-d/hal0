"""Bearer-token store for hal0's auth surface.

On-disk file: ``/etc/hal0/tokens.toml`` (override via ``HAL0_HOME``).

Schema::

    schema_version = 1

    [[tokens]]
    id          = "<uuid4>"
    label       = "openwebui-bridge"
    hash        = "$argon2id$..."
    created_at  = "2026-05-15T12:00:00Z"
    last_used_at = "2026-05-15T13:42:00Z"   # optional; absent until first use
    scope       = "all"                     # "admin" | "all" | "v1-only"

The raw token is shown to the caller exactly once at creation time and
never persisted in plaintext. ``verify(raw_token)`` walks the in-memory
list, matching the prefix ``id`` against the raw token and verifying the
suffix against the argon2id ``hash``.

Token format on the wire::

    hal0_<token_id_8>.<random_secret_43>

Splitting the id into the token string lets us look up the right hash in
O(1) rather than running argon2 against every stored hash on every
request — the secret half still has 256 bits of entropy.

Atomic writes go through :func:`hal0.config.loader.write_toml_atomic` so
a partial write can never lock the user out; the prior ``tokens.toml``
stays intact if the process dies mid-rename.
"""

from __future__ import annotations

import os
import secrets
import time
import tomllib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hal0.auth.passwords import hash_password, verify_password
from hal0.config import paths
from hal0.config.loader import write_toml_atomic
from hal0.errors import Hal0Error

# Bumped when the on-disk tokens.toml shape changes incompatibly.
SCHEMA_VERSION = 1

# Wire format: 8 hex chars of the token id, then '.', then 43 url-safe
# base64 chars of randomness (~256 bits). The leading "hal0_" prefix lets
# log scrubbers and naive secret scanners flag accidental leakage.
_TOKEN_PREFIX = "hal0_"
_ID_LEN = 8
_SECRET_BYTES = 32  # → 43 base64url chars

VALID_SCOPES = frozenset({"admin", "all", "v1-only", "read-only"})


# ── Typed errors ──────────────────────────────────────────────────────────────


class TokenStoreError(Hal0Error):
    """Generic token-store failure (I/O, parse)."""

    code = "auth.store_error"
    status = 500


class DuplicateLabel(Hal0Error):
    """A token with the same label already exists."""

    code = "auth.duplicate_label"
    status = 409


class TokenNotFound(Hal0Error):
    """Revoke / lookup against an unknown token id."""

    code = "auth.token_not_found"
    status = 404


class InvalidScope(Hal0Error):
    """Caller passed an unknown scope literal."""

    code = "auth.invalid_scope"
    status = 400


# ── Data class ────────────────────────────────────────────────────────────────


@dataclass
class Token:
    """In-memory token row.

    The ``hash`` field is the argon2id hash of the secret half of the
    token wire-format. The plaintext secret is never stored.
    """

    id: str
    label: str
    hash: str
    scope: str = "all"
    created_at: str = ""
    last_used_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def metadata(self) -> dict[str, Any]:
        """Public-safe dict for ``GET /api/auth/tokens`` (no hash)."""
        out: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "scope": self.scope,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
        }
        if self.extra:
            out["extra"] = dict(self.extra)
        return out


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    """UTC ISO-8601 with second precision and trailing Z."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_token_store_path() -> Path:
    """``/etc/hal0/tokens.toml`` (or its ``HAL0_HOME`` equivalent)."""
    return paths.etc() / "tokens.toml"


def auth_enabled() -> bool:
    """True iff ``HAL0_AUTH_ENABLED`` is set to a truthy value.

    Default is False so existing installs keep working without changes.
    Flipping the env var (via the installer or Settings UI) gates every
    ``Depends(require_token)`` route.
    """
    val = os.environ.get("HAL0_AUTH_ENABLED", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _split_wire_token(raw: str) -> tuple[str, str] | None:
    """Parse ``hal0_<id8>.<secret>`` into (id, secret). Returns None if malformed."""
    if not raw or not raw.startswith(_TOKEN_PREFIX):
        return None
    body = raw[len(_TOKEN_PREFIX) :]
    if "." not in body:
        return None
    token_id, _, secret = body.partition(".")
    if len(token_id) != _ID_LEN or not secret:
        return None
    return token_id, secret


def _make_wire_token() -> tuple[str, str, str]:
    """Mint a fresh wire token. Returns (token_id, secret, full_wire_token)."""
    token_id = uuid.uuid4().hex[:_ID_LEN]
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    return token_id, secret, f"{_TOKEN_PREFIX}{token_id}.{secret}"


# ── Store ─────────────────────────────────────────────────────────────────────


class TokenStore:
    """Read/write wrapper around tokens.toml.

    Loads lazily on first access; reload() forces a re-read after an
    out-of-band edit. All mutations atomically rewrite the whole file —
    tokens.toml is small (a handful of rows) so we don't bother with
    delta writes, and the atomic-rename invariant is the same one the
    rest of hal0 relies on for slot env files.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else default_token_store_path()
        # ``_loaded`` distinguishes "never read disk" from "read disk and
        # found nothing" so callers don't pay the I/O cost twice on a
        # fresh install where the file genuinely doesn't exist.
        self._loaded = False
        self._tokens: list[Token] = []

    @property
    def path(self) -> Path:
        return self._path

    # ── load / save ──────────────────────────────────────────────────────

    def reload(self) -> None:
        """Force a re-read from disk. Called from POST /api/auth/tokens/reload
        and from tests after writing tokens.toml directly.
        """
        self._loaded = False
        self._tokens = []
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._tokens = []
        if not self._path.exists():
            return
        try:
            with open(self._path, "rb") as f:
                raw = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise TokenStoreError(
                f"failed to parse tokens.toml at {self._path}: {exc}",
                details={"path": str(self._path), "reason": str(exc)},
            ) from exc
        except OSError as exc:
            raise TokenStoreError(
                f"failed to read tokens.toml at {self._path}: {exc}",
                details={"path": str(self._path), "reason": str(exc)},
            ) from exc

        rows = raw.get("tokens", [])
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                tok = Token(
                    id=str(row["id"]),
                    label=str(row["label"]),
                    hash=str(row["hash"]),
                    scope=str(row.get("scope", "all")),
                    created_at=str(row.get("created_at", "")),
                    last_used_at=(
                        str(row["last_used_at"]) if row.get("last_used_at") else None
                    ),
                    extra={
                        k: v
                        for k, v in row.items()
                        if k
                        not in (
                            "id",
                            "label",
                            "hash",
                            "scope",
                            "created_at",
                            "last_used_at",
                        )
                    },
                )
            except KeyError:
                # Skip malformed rows rather than crash the whole store —
                # logging falls to the caller (auth routes).
                continue
            self._tokens.append(tok)

    def _save(self) -> None:
        """Write current state atomically to ``self._path``."""
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "tokens": [],
        }
        for tok in self._tokens:
            row: dict[str, Any] = {
                "id": tok.id,
                "label": tok.label,
                "hash": tok.hash,
                "scope": tok.scope,
                "created_at": tok.created_at,
            }
            if tok.last_used_at:
                row["last_used_at"] = tok.last_used_at
            if tok.extra:
                row.update(tok.extra)
            payload["tokens"].append(row)

        try:
            write_toml_atomic(self._path, payload)
        except OSError as exc:
            raise TokenStoreError(
                f"failed to write tokens.toml at {self._path}: {exc}",
                details={"path": str(self._path), "reason": str(exc)},
            ) from exc

    # ── CRUD ─────────────────────────────────────────────────────────────

    def list(self) -> list[Token]:
        """Return all tokens (in load order)."""
        self._ensure_loaded()
        return list(self._tokens)

    def get(self, token_id: str) -> Token | None:
        """Lookup by id. Returns None if absent."""
        self._ensure_loaded()
        for tok in self._tokens:
            if tok.id == token_id:
                return tok
        return None

    def create(self, label: str, scope: str = "all") -> tuple[Token, str]:
        """Mint a new token. Returns (Token, raw_wire_token).

        The raw token is the only chance to surface the secret to the
        caller — it is NOT recoverable from the store afterwards.
        """
        if scope not in VALID_SCOPES:
            raise InvalidScope(
                f"unknown scope {scope!r}; choose from {sorted(VALID_SCOPES)}",
                details={"scope": scope, "valid": sorted(VALID_SCOPES)},
            )
        label = (label or "").strip()
        if not label:
            raise TokenStoreError("token label must not be empty")

        self._ensure_loaded()
        for existing in self._tokens:
            if existing.label == label:
                raise DuplicateLabel(
                    f"token label {label!r} is already in use",
                    details={"label": label, "existing_id": existing.id},
                )

        token_id, secret, raw = _make_wire_token()
        tok = Token(
            id=token_id,
            label=label,
            hash=hash_password(secret),
            scope=scope,
            created_at=_now_iso(),
            last_used_at=None,
        )
        self._tokens.append(tok)
        self._save()
        return tok, raw

    def revoke(self, token_id: str) -> None:
        """Delete the token by id. Raises TokenNotFound if absent."""
        self._ensure_loaded()
        before = len(self._tokens)
        self._tokens = [t for t in self._tokens if t.id != token_id]
        if len(self._tokens) == before:
            raise TokenNotFound(
                f"no token with id {token_id!r}",
                details={"id": token_id},
            )
        self._save()

    # ── Verification ─────────────────────────────────────────────────────

    def verify(self, raw_token: str) -> Token | None:
        """Return the matching Token if *raw_token* is valid, else None.

        Bumps ``last_used_at`` on a successful match. The bump is best-
        effort: a write failure is logged but doesn't fail the auth path —
        we'd rather authenticate the request than 500 because the disk is
        full.
        """
        parsed = _split_wire_token(raw_token)
        if parsed is None:
            return None
        token_id, secret = parsed
        self._ensure_loaded()
        for tok in self._tokens:
            if tok.id != token_id:
                continue
            if not verify_password(tok.hash, secret):
                return None
            tok.last_used_at = _now_iso()
            try:
                self._save()
            except TokenStoreError:
                # Don't let a metadata-write failure 401 a valid token —
                # the request can still be served; the timestamp is a
                # convenience, not a security boundary.
                pass
            return tok
        return None


# ── App-state singleton helpers ──────────────────────────────────────────────
# The TokenStore is cheap to construct but expensive to keep re-loading from
# disk on every request. The FastAPI dependency in
# hal0.api.middleware.auth caches one instance on app.state.


def get_or_create_store(app_state: Any) -> TokenStore:
    """Return ``app_state.token_store`` or initialise a fresh one.

    Keyed on the FastAPI app's state so tests with a fresh app per
    function get a fresh store. Production keeps the singleton for the
    process's lifetime; tokens.toml hot-edits flow through
    ``store.reload()``.
    """
    store = getattr(app_state, "token_store", None)
    if store is None:
        store = TokenStore()
        app_state.token_store = store
    return store


# ── Throwaway helper for tests / probes ──────────────────────────────────────


def _utcnow_unix() -> float:
    """time.time() factored out for monkeypatch in tests."""
    return time.time()


__all__ = [
    "DuplicateLabel",
    "InvalidScope",
    "SCHEMA_VERSION",
    "Token",
    "TokenNotFound",
    "TokenStore",
    "TokenStoreError",
    "VALID_SCOPES",
    "auth_enabled",
    "default_token_store_path",
    "get_or_create_store",
]

"""Argon2id wrapper tests."""

from __future__ import annotations

import pytest

from hal0.auth.passwords import hash_password, verify_password


def test_hash_round_trip() -> None:
    h = hash_password("hunter2")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "hunter2") is True


def test_verify_wrong_password() -> None:
    h = hash_password("right")
    assert verify_password(h, "wrong") is False


def test_verify_returns_false_on_malformed_hash() -> None:
    # Don't blow up — bad hash means "doesn't match", surface a 401 not a 500.
    assert verify_password("not-a-hash", "anything") is False


def test_verify_empty_inputs() -> None:
    assert verify_password("", "x") is False
    assert verify_password("$argon2id$...", "") is False


def test_empty_password_rejected_at_hash_time() -> None:
    with pytest.raises(ValueError):
        hash_password("")


def test_unique_hashes_for_same_password() -> None:
    """argon2 uses a per-call random salt — same input must produce different hashes."""
    a = hash_password("same")
    b = hash_password("same")
    assert a != b
    # Both still verify.
    assert verify_password(a, "same") is True
    assert verify_password(b, "same") is True

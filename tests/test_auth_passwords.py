"""Unit tests for sonya.auth.passwords."""

from __future__ import annotations

import pytest

from sonya.auth.passwords import hash_password, verify_password


def test_hash_password_round_trip() -> None:
    h = hash_password("hunter2-secret")
    assert verify_password("hunter2-secret", h) is True


def test_hash_password_rejects_wrong_password() -> None:
    h = hash_password("correct-horse-battery-staple")
    assert verify_password("not-the-same", h) is False


def test_hash_password_unique_salts() -> None:
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b
    assert verify_password("same-password", a) is True
    assert verify_password("same-password", b) is True


def test_hash_password_rejects_empty() -> None:
    with pytest.raises(ValueError):
        hash_password("")


def test_verify_password_handles_garbage_hash() -> None:
    assert verify_password("anything", b"not-a-real-bcrypt-hash") is False


def test_verify_password_empty_inputs() -> None:
    assert verify_password("", b"") is False
    assert verify_password("p", b"") is False
    assert verify_password("", b"$2b$12$" + b"x" * 53) is False

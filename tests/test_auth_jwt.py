"""Unit tests for sonya.auth.jwt."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sonya.auth.jwt import InvalidTokenError, decode_token, encode_token
from sonya.config import Settings

_TEST_SECRET = "test-secret-please-rotate-x" * 2  # >32 bytes — silences pyjwt warning


def _settings(secret: str | None = _TEST_SECRET, ttl: int = 3600) -> Settings:
    return Settings(auth_jwt_secret=secret, auth_jwt_ttl_seconds=ttl)


def test_encode_decode_round_trip() -> None:
    s = _settings()
    token = encode_token(user_id=42, owner_id=7, role="admin", settings=s)
    claims = decode_token(token, settings=s)
    assert claims.user_id == 42
    assert claims.owner_id == 7
    assert claims.role == "admin"
    assert claims.expires_at > datetime.now(UTC)


def test_decode_rejects_empty_token() -> None:
    s = _settings()
    with pytest.raises(InvalidTokenError):
        decode_token("", settings=s)


def test_decode_rejects_garbage_token() -> None:
    s = _settings()
    with pytest.raises(InvalidTokenError):
        decode_token("not.a.jwt", settings=s)


def test_decode_rejects_expired_token() -> None:
    s = _settings(ttl=10)
    issued = datetime.now(UTC) - timedelta(hours=1)
    token = encode_token(user_id=1, owner_id=1, role="admin", settings=s, issued_at=issued)
    with pytest.raises(InvalidTokenError, match="expired"):
        decode_token(token, settings=s)


def test_decode_rejects_wrong_signature() -> None:
    s_a = _settings(secret="secret-a-" * 8)
    s_b = _settings(secret="secret-b-" * 8)
    token = encode_token(user_id=1, owner_id=1, role="admin", settings=s_a)
    with pytest.raises(InvalidTokenError):
        decode_token(token, settings=s_b)


def test_encode_requires_secret() -> None:
    s = _settings(secret=None)
    with pytest.raises(InvalidTokenError, match="auth_jwt_secret"):
        encode_token(user_id=1, owner_id=1, role="admin", settings=s)


def test_decode_requires_secret() -> None:
    s_signing = _settings(secret="signing-" * 8)
    s_no_secret = _settings(secret=None)
    token = encode_token(user_id=1, owner_id=1, role="admin", settings=s_signing)
    with pytest.raises(InvalidTokenError):
        decode_token(token, settings=s_no_secret)

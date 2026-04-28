"""Unit tests for the symmetric-encryption helpers in `sonya.combine.security`."""

from __future__ import annotations

from cryptography.fernet import Fernet

from sonya.combine import security
from sonya.config import Settings


def _settings_with_key(key: str | None) -> Settings:
    s = Settings()
    s.combine_secret_key = key
    return s


def test_no_key_means_passthrough() -> None:
    s = _settings_with_key(None)
    token = security.encrypt_str("hello", settings=s)
    assert token == b"hello"
    assert security.decrypt_str(token, settings=s) == "hello"


def test_round_trip_with_key() -> None:
    key = Fernet.generate_key().decode()
    s = _settings_with_key(key)

    token = security.encrypt_str("super-secret", settings=s)
    assert token is not None
    assert token != b"super-secret"
    assert security.decrypt_str(token, settings=s) == "super-secret"


def test_decrypt_falls_back_to_raw_when_legacy_unencrypted() -> None:
    """Rows written before a key existed must keep working after one is added."""
    no_key = _settings_with_key(None)
    legacy_token = security.encrypt_str("legacy", settings=no_key)

    keyed = _settings_with_key(Fernet.generate_key().decode())
    # Should not raise and should return the original plaintext.
    assert security.decrypt_str(legacy_token, settings=keyed) == "legacy"


def test_none_in_none_out() -> None:
    s = _settings_with_key(Fernet.generate_key().decode())
    assert security.encrypt_str(None, settings=s) is None
    assert security.decrypt_str(None, settings=s) is None
    assert security.encrypt_bytes(None, settings=s) is None
    assert security.decrypt_bytes(None, settings=s) is None


def test_require_cipher_raises_without_key() -> None:
    import pytest

    with pytest.raises(security.CipherUnavailable):
        security.require_cipher(_settings_with_key(None))


def test_require_cipher_returns_with_key() -> None:
    s = _settings_with_key(Fernet.generate_key().decode())
    assert security.require_cipher(s) is not None

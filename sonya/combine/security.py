"""Symmetric encryption helpers for combine secrets.

Wraps :mod:`cryptography.fernet` so callers don't import it directly. Used
for two payloads:

* :class:`Account.session_blob` — the Telethon ``StringSession`` bytes.
* :class:`Proxy.password` — outbound proxy auth password.

When :attr:`Settings.combine_secret_key` is unset, the helpers become a
no-op pass-through. That's intentional for local dev — production
deployments must set the key (validated at startup by
:func:`require_cipher`).
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from sonya.config import Settings, get_settings


class CipherUnavailable(RuntimeError):
    """Raised when the caller required a cipher but no key is configured."""


def _build_cipher(settings: Settings) -> Fernet | None:
    key = settings.combine_secret_key
    if not key:
        return None
    return Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def get_cipher(settings: Settings | None = None) -> Fernet | None:
    """Return a configured Fernet, or ``None`` if encryption is disabled."""
    return _build_cipher(settings or get_settings())


def require_cipher(settings: Settings | None = None) -> Fernet:
    """Like :func:`get_cipher` but raises if encryption isn't configured."""
    cipher = get_cipher(settings)
    if cipher is None:
        raise CipherUnavailable(
            "combine_secret_key is not set; cannot encrypt/decrypt secrets. "
            'Generate one with `python -c "from cryptography.fernet import '
            'Fernet; print(Fernet.generate_key().decode())"` and add it to .env.'
        )
    return cipher


def encrypt_str(plaintext: str | None, *, settings: Settings | None = None) -> bytes | None:
    """Encrypt a UTF-8 string. ``None`` in ``None`` out."""
    if plaintext is None:
        return None
    cipher = get_cipher(settings)
    raw = plaintext.encode("utf-8")
    if cipher is None:
        return raw
    return cipher.encrypt(raw)


def decrypt_str(token: bytes | None, *, settings: Settings | None = None) -> str | None:
    """Decrypt a Fernet token to a UTF-8 string. ``None`` in ``None`` out.

    If decryption fails (no key, wrong key, or unencrypted legacy bytes),
    the function falls back to interpreting ``token`` as raw UTF-8 — that
    way local-dev rows written without a key keep working when a key is
    later added.
    """
    if token is None:
        return None
    cipher = get_cipher(settings)
    if cipher is not None:
        try:
            return cipher.decrypt(token).decode("utf-8")
        except InvalidToken:
            pass
    try:
        return bytes(token).decode("utf-8")
    except UnicodeDecodeError:
        return None


def encrypt_bytes(plaintext: bytes | None, *, settings: Settings | None = None) -> bytes | None:
    """Encrypt arbitrary bytes. ``None`` in ``None`` out."""
    if plaintext is None:
        return None
    cipher = get_cipher(settings)
    if cipher is None:
        return plaintext
    return cipher.encrypt(plaintext)


def decrypt_bytes(token: bytes | None, *, settings: Settings | None = None) -> bytes | None:
    """Decrypt arbitrary bytes. Mirrors :func:`decrypt_str`'s fallback logic."""
    if token is None:
        return None
    cipher = get_cipher(settings)
    if cipher is None:
        return bytes(token)
    try:
        return cipher.decrypt(token)
    except InvalidToken:
        return bytes(token)


__all__ = [
    "CipherUnavailable",
    "decrypt_bytes",
    "decrypt_str",
    "encrypt_bytes",
    "encrypt_str",
    "get_cipher",
    "require_cipher",
]

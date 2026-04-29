"""Password hashing primitives backed by bcrypt.

bcrypt is intentionally chosen over scrypt/argon2 because it's a single
small dependency (no native build deps beyond a wheel) and the work
factor is configurable per-deployment via :data:`BCRYPT_ROUNDS`.

Hashes are stored as raw bytes (``LargeBinary``) so the column can hold
future hashers without a migration — :func:`verify_password` dispatches
on the magic prefix in the stored hash.
"""

from __future__ import annotations

import bcrypt

# 12 is the bcrypt default and a good 2026 baseline (~250ms on a single
# modern core). Tests can patch this to a smaller value (4) if they
# create lots of users — see ``conftest`` if/when that becomes a problem.
BCRYPT_ROUNDS = 12


def hash_password(plain: str) -> bytes:
    """Hash a plaintext password using bcrypt with :data:`BCRYPT_ROUNDS`.

    Returns the raw 60-byte bcrypt hash (printable ASCII inside).
    """

    if not plain:
        raise ValueError("password must be non-empty")
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(plain.encode("utf-8"), salt)


def verify_password(plain: str, stored_hash: bytes) -> bool:
    """Constant-time check of ``plain`` against a stored bcrypt hash.

    Returns ``False`` for malformed hashes instead of raising — callers
    can treat invalid stored data the same as a bad password.
    """

    if not plain or not stored_hash:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), stored_hash)
    except ValueError:
        # bcrypt raises on malformed hashes; treat as failure.
        return False

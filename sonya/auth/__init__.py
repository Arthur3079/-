"""Auth subsystem: password hashing, JWT tokens, user repository.

The combine REST endpoints already accept ``owner_id`` everywhere — auth
just resolves which owner the current request belongs to. The JWT layer
is intentionally kept thin: HS256-signed access tokens with a short TTL,
no refresh tokens (UI just re-logs-in when the access token expires).
"""

from sonya.auth.jwt import (
    InvalidTokenError,
    TokenClaims,
    decode_token,
    encode_token,
)
from sonya.auth.passwords import hash_password, verify_password
from sonya.auth.repository import (
    LoginAlreadyTakenError,
    create_user,
    get_user_by_id,
    get_user_by_login,
)

__all__ = [
    "InvalidTokenError",
    "LoginAlreadyTakenError",
    "TokenClaims",
    "create_user",
    "decode_token",
    "encode_token",
    "get_user_by_id",
    "get_user_by_login",
    "hash_password",
    "verify_password",
]

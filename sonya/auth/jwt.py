"""HS256 JWT helpers for access tokens.

The token carries the minimal info the request middleware needs:
``user_id``, ``owner_id``, ``role``. Everything else is loaded from the DB.

The signing secret is taken from :class:`Settings`. A missing/empty
secret raises at encode/decode time so production deployments fail
loudly instead of silently using a constant key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt as _jwt

from sonya.config import Settings, get_settings

JWT_ALGORITHM = "HS256"
DEFAULT_TOKEN_TTL_SECONDS = 60 * 60 * 12  # 12 hours


class InvalidTokenError(Exception):
    """Raised by :func:`decode_token` for malformed / expired / mis-signed tokens."""


@dataclass(frozen=True)
class TokenClaims:
    """Decoded payload of a Sonya access token."""

    user_id: int
    owner_id: int
    role: str
    expires_at: datetime


def _resolve_secret(settings: Settings | None) -> str:
    settings = settings or get_settings()
    secret = settings.auth_jwt_secret
    if not secret:
        raise InvalidTokenError("auth_jwt_secret is not configured — set AUTH_JWT_SECRET in .env")
    return secret


def encode_token(
    *,
    user_id: int,
    owner_id: int,
    role: str,
    ttl_seconds: int | None = None,
    settings: Settings | None = None,
    issued_at: datetime | None = None,
) -> str:
    """Encode a signed access token for ``user_id``.

    ``ttl_seconds`` defaults to ``settings.auth_jwt_ttl_seconds`` (or 12h
    if that is also unset). ``issued_at`` is injected for tests; defaults
    to ``datetime.now(UTC)``.
    """

    s = settings or get_settings()
    ttl = ttl_seconds if ttl_seconds is not None else s.auth_jwt_ttl_seconds
    iat = issued_at or datetime.now(UTC)
    exp = iat + timedelta(seconds=ttl)
    payload = {
        "sub": str(user_id),
        "owner_id": owner_id,
        "role": role,
        "iat": int(iat.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return _jwt.encode(payload, _resolve_secret(s), algorithm=JWT_ALGORITHM)


def decode_token(token: str, *, settings: Settings | None = None) -> TokenClaims:
    """Decode and validate ``token``.

    Raises :class:`InvalidTokenError` for any error condition (bad
    signature, expired, malformed, missing fields). Callers should turn
    that into HTTP 401.
    """

    if not token:
        raise InvalidTokenError("empty token")
    s = settings or get_settings()
    try:
        payload = _jwt.decode(
            token,
            _resolve_secret(s),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "owner_id", "role", "exp"]},
        )
    except _jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("token expired") from exc
    except _jwt.InvalidTokenError as exc:
        raise InvalidTokenError(f"invalid token: {exc}") from exc

    try:
        user_id = int(payload["sub"])
        owner_id = int(payload["owner_id"])
        role = str(payload["role"])
        exp = datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidTokenError(f"malformed claims: {exc}") from exc

    return TokenClaims(user_id=user_id, owner_id=owner_id, role=role, expires_at=exp)

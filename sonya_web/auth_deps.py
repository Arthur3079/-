"""FastAPI dependencies for the auth layer.

Two access patterns:

* ``get_current_user_required`` — protects routes that *must* have a
  logged-in user. Returns 401 on missing/invalid token.
* ``get_current_owner_id`` — resolves the tenant for combine routers.
  When auth is **enabled** (``auth_jwt_secret`` set in settings) and a
  Bearer token is present, returns the user's owner_id; otherwise falls
  back to ``DEFAULT_OWNER_ID`` so unauthenticated dev / test flows keep
  working.

Routers that previously called ``ensure_default_owner(session)`` should
now ``Depends(ensure_request_owner)`` which materialises the row for the
*current* owner_id.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.auth.jwt import InvalidTokenError, TokenClaims, decode_token
from sonya.auth.repository import get_user_by_id
from sonya.combine.accounts.repository import DEFAULT_OWNER_ID, ensure_default_owner
from sonya.config import Settings, get_settings
from sonya.db.models_auth import User
from sonya.db.models_combine import Owner
from sonya_web.deps import get_session


def _extract_bearer(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def _try_decode(authorization: str | None, settings: Settings) -> TokenClaims | None:
    """Return decoded claims, or ``None`` if no Authorization header was sent.

    Raises :class:`HTTPException` 401 if a token *was* sent but is invalid.
    Returns ``None`` only when no token at all is present, so callers can
    decide whether absence of a token is allowed.
    """

    token = _extract_bearer(authorization)
    if token is None:
        return None
    if not settings.auth_jwt_secret:
        # Token sent but server has no secret configured — treat as invalid
        # rather than silently ignoring.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="auth disabled on this server",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_token(token, settings=settings)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user_optional(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    """Return the currently logged-in :class:`User`, or ``None`` if no token."""

    settings = get_settings()
    claims = _try_decode(authorization, settings)
    if claims is None:
        return None
    user = await get_user_by_id(session, claims.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user is gone or disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_user_required(
    user: Annotated[User | None, Depends(get_current_user_optional)],
) -> User:
    """Return the currently logged-in user, or 401 if absent."""

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_owner_id(
    user: Annotated[User | None, Depends(get_current_user_optional)],
) -> int:
    """Resolve the owner_id for the current request.

    * Authenticated request → the JWT user's ``owner_id``.
    * No Authorization header → ``DEFAULT_OWNER_ID`` (single-tenant /
      legacy / unauthenticated test mode).
    """

    if user is None:
        return DEFAULT_OWNER_ID
    return user.owner_id


async def ensure_request_owner(
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> Owner:
    """Materialise the owner row for the current request.

    Replaces the explicit ``ensure_default_owner(session)`` calls that
    used to sit at the top of every combine endpoint. For
    ``DEFAULT_OWNER_ID`` this is a no-op idempotent insert (matches the
    previous behaviour); for any other owner_id the row must already
    exist (created by the auth flow on register).
    """

    if owner_id == DEFAULT_OWNER_ID:
        return await ensure_default_owner(session)
    owner = await session.get(Owner, owner_id)
    if owner is None:
        # Should not happen in practice — owner_id comes from a JWT issued
        # at register-time when the owner row was created. If it does
        # happen, treat as authentication failure rather than 500.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="owner row vanished — please re-login",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return owner

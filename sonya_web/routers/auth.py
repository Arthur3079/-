"""REST router for the JWT-based admin auth.

Mounted at ``/api/auth``. Endpoints:

* ``POST /register`` — bootstrap a new owner + user, returns access token.
  Disabled when ``settings.auth_register_enabled`` is False.
* ``POST /login``    — verify credentials, returns access token.
* ``GET  /me``       — return the current user info (requires Bearer).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.auth import (
    LoginAlreadyTakenError,
    create_user,
    encode_token,
    get_user_by_login,
    hash_password,
    verify_password,
)
from sonya.config import get_settings
from sonya.db.models_auth import User, UserRole
from sonya.db.models_combine import Owner
from sonya_web.auth_deps import get_current_user_required
from sonya_web.deps import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------- schemas ----------


class TokenOut(BaseModel):
    """Response shape for ``/login`` and ``/register``."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: int
    login: str
    owner_id: int
    role: str
    is_active: bool


class RegisterIn(BaseModel):
    login: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    workspace_name: str = Field(default="default", min_length=1, max_length=64)


class LoginIn(BaseModel):
    login: str
    password: str


# ---------- helpers ----------


def _user_to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        login=user.login,
        owner_id=user.owner_id,
        role=str(user.role.value if hasattr(user.role, "value") else user.role),
        is_active=user.is_active,
    )


def _make_token(user: User) -> TokenOut:
    settings = get_settings()
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = encode_token(
        user_id=user.id,
        owner_id=user.owner_id,
        role=role,
        settings=settings,
    )
    return TokenOut(access_token=token, expires_in=settings.auth_jwt_ttl_seconds)


# ---------- endpoints ----------


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(
    payload: RegisterIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenOut:
    settings = get_settings()
    if not settings.auth_register_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="self-registration disabled",
        )
    if not settings.auth_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth_jwt_secret is not configured",
        )

    # New owner workspace per registered user — first user is the admin.
    owner = Owner(name=payload.workspace_name)
    session.add(owner)
    await session.flush()

    try:
        user = await create_user(
            session,
            login=payload.login,
            password_hash=hash_password(payload.password),
            owner_id=owner.id,
            role=UserRole.ADMIN,
        )
    except LoginAlreadyTakenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="login already taken",
        ) from exc

    await session.commit()
    return _make_token(user)


@router.post("/login", response_model=TokenOut)
async def login(
    payload: LoginIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenOut:
    settings = get_settings()
    if not settings.auth_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth_jwt_secret is not configured",
        )

    user = await get_user_by_login(session, payload.login)
    # Always run verify even if user is missing, to keep timing similar.
    if user is None or not user.is_active:
        # Burn one bcrypt round so registered/non-registered logins look the
        # same to a remote attacker.
        verify_password(payload.password, b"$2b$12$" + b"x" * 53)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )
    return _make_token(user)


@router.get("/me", response_model=UserOut)
async def me(
    user: Annotated[User, Depends(get_current_user_required)],
) -> UserOut:
    return _user_to_out(user)

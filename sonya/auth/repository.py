"""User repository — async SQLAlchemy queries for the ``users`` table."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models_auth import User, UserRole


class LoginAlreadyTakenError(Exception):
    """Raised when :func:`create_user` collides with an existing login."""


async def get_user_by_login(session: AsyncSession, login: str) -> User | None:
    """Look up a user by case-sensitive login. Returns ``None`` if missing."""
    res = await session.execute(select(User).where(User.login == login))
    return res.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    """Look up a user by primary key."""
    return await session.get(User, user_id)


async def create_user(
    session: AsyncSession,
    *,
    login: str,
    password_hash: bytes,
    owner_id: int,
    role: UserRole = UserRole.MEMBER,
    is_active: bool = True,
) -> User:
    """Insert a new user row.

    Caller is responsible for the surrounding transaction (commit or
    rollback). Raises :class:`LoginAlreadyTakenError` if the unique
    ``login`` constraint fires; the session is rolled back to a clean
    state in that case so the caller can react and continue.
    """

    user = User(
        login=login,
        password_hash=password_hash,
        owner_id=owner_id,
        role=role,
        is_active=is_active,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise LoginAlreadyTakenError(login) from exc
    return user

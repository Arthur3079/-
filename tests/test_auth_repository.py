"""Unit tests for sonya.auth.repository."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sonya.auth.repository import (
    LoginAlreadyTakenError,
    create_user,
    get_user_by_id,
    get_user_by_login,
)
from sonya.db.base import Base
from sonya.db.models_auth import UserRole
from sonya.db.models_combine import Owner  # noqa: F401 — needed for FK metadata


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        s.add(Owner(id=1, name="default"))
        await s.flush()
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_user_basic(session: AsyncSession) -> None:
    user = await create_user(
        session,
        login="alice",
        password_hash=b"$2b$12$xxxx",
        owner_id=1,
        role=UserRole.ADMIN,
    )
    assert user.id is not None
    assert user.login == "alice"
    assert user.owner_id == 1
    assert user.role == UserRole.ADMIN


@pytest.mark.asyncio
async def test_get_user_by_login(session: AsyncSession) -> None:
    await create_user(session, login="bob", password_hash=b"hash", owner_id=1)
    found = await get_user_by_login(session, "bob")
    assert found is not None
    assert found.login == "bob"
    missing = await get_user_by_login(session, "nobody")
    assert missing is None


@pytest.mark.asyncio
async def test_get_user_by_id(session: AsyncSession) -> None:
    user = await create_user(session, login="carol", password_hash=b"hash", owner_id=1)
    found = await get_user_by_id(session, user.id)
    assert found is not None
    assert found.login == "carol"
    assert await get_user_by_id(session, 99999) is None


@pytest.mark.asyncio
async def test_create_user_duplicate_login(session: AsyncSession) -> None:
    await create_user(session, login="dave", password_hash=b"hash", owner_id=1)
    with pytest.raises(LoginAlreadyTakenError):
        await create_user(session, login="dave", password_hash=b"hash2", owner_id=1)

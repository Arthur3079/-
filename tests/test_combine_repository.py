"""Unit tests for `sonya.combine.accounts.repository` against an in-memory DB."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sonya.combine.accounts import repository as repo
from sonya.config import get_settings
from sonya.db.base import Base
from sonya.db.models_combine import (  # noqa: F401 — needed to register tables
    Account,
    AccountRole,
    AccountStatus,
    Owner,
    Proxy,
    ProxyType,
)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_default_owner_is_idempotent(session: AsyncSession) -> None:
    o1 = await repo.ensure_default_owner(session)
    o2 = await repo.ensure_default_owner(session)
    assert o1.id == o2.id == 1
    assert o1.name == "default"


@pytest.mark.asyncio
async def test_account_lifecycle(session: AsyncSession) -> None:
    await repo.ensure_default_owner(session)
    acc = await repo.create_account(session, phone="+1000000001", api_id=1, api_hash="h")
    assert acc.status == AccountStatus.NEW

    fetched = await repo.get_account(session, acc.id)
    assert fetched is not None and fetched.phone == "+1000000001"

    by_phone = await repo.get_account_by_phone(session, "+1000000001")
    assert by_phone is not None and by_phone.id == acc.id

    await repo.update_account(session, acc, role=AccountRole.COMMENTER, note="x")
    assert acc.role == AccountRole.COMMENTER
    assert acc.note == "x"

    await repo.set_account_session(
        session,
        acc,
        session_string="SS",
        tg_user_id=42,
        username="alice",
    )
    assert acc.status == AccountStatus.ACTIVE
    assert acc.tg_user_id == 42
    assert acc.username == "alice"
    assert acc.session_blob is not None
    assert repo.account_session_string(acc) == "SS"

    await repo.clear_account_session(session, acc)
    assert acc.session_blob is None
    assert acc.status == AccountStatus.NEW


@pytest.mark.asyncio
async def test_account_session_encrypted_when_key_set(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("COMBINE_SECRET_KEY", key)
    get_settings.cache_clear()
    try:
        await repo.ensure_default_owner(session)
        acc = await repo.create_account(session, phone="+1000000099")
        await repo.set_account_session(session, acc, session_string="MY-STRING-SESSION")

        # Stored bytes are NOT the plaintext.
        assert acc.session_blob is not None
        assert b"MY-STRING-SESSION" not in bytes(acc.session_blob)
        # But the helper decrypts cleanly.
        assert repo.account_session_string(acc) == "MY-STRING-SESSION"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_proxy_lifecycle_and_password_encryption(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("COMBINE_SECRET_KEY", key)
    get_settings.cache_clear()
    try:
        await repo.ensure_default_owner(session)
        proxy = await repo.create_proxy(
            session,
            type=ProxyType.SOCKS5,
            host="p.example.com",
            port=1080,
            username="u",
            password="hunter2",
        )
        assert proxy.password is not None
        assert "hunter2" not in proxy.password  # encrypted
        assert repo.proxy_password_plaintext(proxy) == "hunter2"

        await repo.update_proxy(session, proxy, password="new-pw", note="updated")
        assert proxy.note == "updated"
        assert repo.proxy_password_plaintext(proxy) == "new-pw"

        await repo.delete_proxy(session, proxy)
        assert await repo.get_proxy(session, proxy.id) is None
    finally:
        get_settings.cache_clear()

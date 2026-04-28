"""Юнит-тесты для sonya.crm.repository (in-memory sqlite)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.crm.repository import get_or_create_client, save_message
from sonya.db import models  # noqa: F401  (регистрирует модели в metadata)
from sonya.db.base import Base
from sonya.db.models import MessageDirection, MessageMediaType


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_create_then_lookup(session) -> None:
    client = await get_or_create_client(
        session, fan_id=42, username="bob", first_name="Bob", last_name=None
    )
    assert client.fan_id == 42
    assert client.display_name == "Bob"

    again = await get_or_create_client(
        session, fan_id=42, username="bob_new", first_name="Bob", last_name="Smith"
    )
    assert again.fan_id == client.fan_id
    assert again.username == "bob_new"
    assert again.last_name == "Smith"


async def test_user_clearing_username_propagates_to_db(session) -> None:
    """Если фан удалил юзернейм/фамилию в Telegram — в БД тоже должно стать None."""
    await get_or_create_client(
        session, fan_id=99, username="alice", first_name="Alice", last_name="Smith"
    )
    cleared = await get_or_create_client(
        session, fan_id=99, username=None, first_name="Alice", last_name=None
    )
    assert cleared.username is None
    assert cleared.last_name is None


async def test_display_name_refreshes_after_rename(session) -> None:
    """Если фан добавил/сменил фамилию — display_name должен обновиться."""
    first = await get_or_create_client(
        session, fan_id=55, username="bob", first_name="Bob", last_name=None
    )
    assert first.display_name == "Bob"

    renamed = await get_or_create_client(
        session, fan_id=55, username="bob", first_name="Bob", last_name="Smith"
    )
    assert renamed.display_name == "Bob Smith"


async def test_display_name_kept_when_user_has_nothing(session) -> None:
    """Если новые данные совсем пустые — оставляем прошлый display_name."""
    await get_or_create_client(
        session, fan_id=66, username="charlie", first_name="Charlie", last_name=None
    )
    blank = await get_or_create_client(
        session, fan_id=66, username=None, first_name=None, last_name=None
    )
    assert blank.display_name == "Charlie"


async def test_display_name_falls_back_to_username(session) -> None:
    client = await get_or_create_client(
        session, fan_id=1, username="anon", first_name=None, last_name=None
    )
    assert client.display_name == "@anon"


async def test_save_messages_both_directions(session) -> None:
    await get_or_create_client(session, fan_id=7, username="x", first_name="X", last_name=None)
    incoming = await save_message(
        session,
        fan_id=7,
        tg_message_id=100,
        direction=MessageDirection.INCOMING,
        content="hi",
    )
    outgoing = await save_message(
        session,
        fan_id=7,
        tg_message_id=101,
        direction=MessageDirection.OUTGOING,
        content="[stub] received: hi",
        media_type=MessageMediaType.TEXT,
    )
    assert incoming.id != outgoing.id
    assert incoming.direction is MessageDirection.INCOMING
    assert outgoing.direction is MessageDirection.OUTGOING
    assert outgoing.content == "[stub] received: hi"

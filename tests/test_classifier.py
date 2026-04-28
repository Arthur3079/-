"""Tests for sonya.crm.classifier.classify_fan."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.crm.classifier import (
    GHOST_DAYS,
    NEWCOMER_MAX_INCOMING,
    WHALE_LIFETIME_SPEND,
    FanTypeLite,
    classify_fan,
)
from sonya.crm.repository import get_or_create_client, save_message
from sonya.db import models  # noqa: F401
from sonya.db.base import Base
from sonya.db.models import MessageDirection


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _make_client(session, fan_id=1):
    c = await get_or_create_client(
        session, fan_id=fan_id, username="x", first_name="X", last_name=None
    )
    await session.commit()
    return c


async def test_newcomer_default(session) -> None:
    client = await _make_client(session)
    res = await classify_fan(session, client=client)
    assert res.fan_type is FanTypeLite.NEWCOMER


async def test_regular_after_threshold(session) -> None:
    client = await _make_client(session)
    # send NEWCOMER_MAX_INCOMING+1 incoming messages
    for i in range(NEWCOMER_MAX_INCOMING + 1):
        await save_message(
            session,
            fan_id=client.fan_id,
            tg_message_id=i,
            direction=MessageDirection.INCOMING,
            content=f"msg {i}",
        )
    await session.commit()
    res = await classify_fan(session, client=client)
    assert res.fan_type is FanTypeLite.REGULAR


async def test_whale_via_lifetime_spend(session) -> None:
    client = await _make_client(session)
    client.total_spend_lifetime = WHALE_LIFETIME_SPEND + 50.0
    await session.commit()
    res = await classify_fan(session, client=client)
    assert res.fan_type is FanTypeLite.WHALE


async def test_ghost_via_last_active(session) -> None:
    client = await _make_client(session)
    client.last_active = datetime.now(UTC) - timedelta(days=GHOST_DAYS + 1)
    await session.commit()
    res = await classify_fan(session, client=client)
    assert res.fan_type is FanTypeLite.GHOST


async def test_risky_beats_everything(session) -> None:
    client = await _make_client(session)
    # Configure as a whale + ghost + risky → should still be RISKY.
    client.total_spend_lifetime = WHALE_LIFETIME_SPEND * 10
    client.last_active = datetime.now(UTC) - timedelta(days=30)
    client.flags = "vulnerable_lite,off_platform"
    await session.commit()
    res = await classify_fan(session, client=client)
    assert res.fan_type is FanTypeLite.RISKY
    assert any("flag:" in r for r in res.reasons)


async def test_ghost_beats_whale(session) -> None:
    client = await _make_client(session)
    client.total_spend_lifetime = WHALE_LIFETIME_SPEND * 10
    client.last_active = datetime.now(UTC) - timedelta(days=GHOST_DAYS + 1)
    await session.commit()
    res = await classify_fan(session, client=client)
    assert res.fan_type is FanTypeLite.GHOST


async def test_recent_active_not_ghost(session) -> None:
    client = await _make_client(session)
    client.last_active = datetime.now(UTC) - timedelta(hours=1)
    await session.commit()
    res = await classify_fan(session, client=client)
    assert res.fan_type is not FanTypeLite.GHOST

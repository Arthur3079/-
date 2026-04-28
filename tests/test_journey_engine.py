"""Tests for `JourneyEngine.classify_stage` and persistence wrapper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.crm.repository import get_or_create_client
from sonya.db import models  # noqa: F401
from sonya.db.base import Base
from sonya.journey import Stage
from sonya.journey.engine import (
    AFTERCARE_WINDOW,
    GHOST_THRESHOLD,
    OFFER_PENDING_WINDOW,
    JourneyEngine,
    classify_stage,
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _client(session, **overrides):
    c = await get_or_create_client(
        session, fan_id=overrides.pop("fan_id", 1), username="u", first_name="U", last_name=None
    )
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


NOW = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)


async def test_handoff_short_circuits(session) -> None:
    c = await _client(session, handoff_required=True)
    assert classify_stage(c, recent_inbound_count=99, now=NOW) is Stage.HANDOFF


async def test_active_suppression_short_circuits(session) -> None:
    c = await _client(session, suppression_until=NOW + timedelta(hours=1))
    assert classify_stage(c, recent_inbound_count=99, now=NOW) is Stage.PAUSED_SAFETY


async def test_expired_suppression_does_not_pause(session) -> None:
    c = await _client(session, suppression_until=NOW - timedelta(hours=1))
    assert classify_stage(c, recent_inbound_count=0, now=NOW) is Stage.WELCOME


async def test_offer_pending_when_offer_recent_and_no_purchase(session) -> None:
    c = await _client(
        session,
        last_offer_at=NOW - timedelta(hours=2),
        last_purchase_at=None,
    )
    assert classify_stage(c, recent_inbound_count=10, now=NOW) is Stage.OFFER_PENDING


async def test_offer_pending_resolved_by_purchase(session) -> None:
    c = await _client(
        session,
        last_offer_at=NOW - timedelta(hours=2),
        last_purchase_at=NOW - timedelta(hours=1),
    )
    # Purchased after the offer → moves to AFTERCARE.
    assert classify_stage(c, recent_inbound_count=10, now=NOW) is Stage.AFTERCARE


async def test_aftercare_window(session) -> None:
    c = await _client(session, last_purchase_at=NOW - timedelta(days=2))
    assert classify_stage(c, recent_inbound_count=99, now=NOW) is Stage.AFTERCARE


async def test_repeat_ready_after_aftercare_window(session) -> None:
    c = await _client(session, last_purchase_at=NOW - AFTERCARE_WINDOW - timedelta(hours=1))
    assert classify_stage(c, recent_inbound_count=99, now=NOW) is Stage.REPEAT_READY


async def test_ghost_after_threshold(session) -> None:
    c = await _client(session, last_inbound_at=NOW - GHOST_THRESHOLD - timedelta(hours=1))
    assert classify_stage(c, recent_inbound_count=10, now=NOW) is Stage.GHOST


async def test_welcome_warmup_qualify_progression(session) -> None:
    c = await _client(session)
    assert classify_stage(c, recent_inbound_count=0, now=NOW) is Stage.WELCOME
    assert classify_stage(c, recent_inbound_count=2, now=NOW) is Stage.WARMUP
    assert classify_stage(c, recent_inbound_count=5, now=NOW) is Stage.QUALIFY


async def test_classify_and_persist_writes_stage(session) -> None:
    c = await get_or_create_client(session, fan_id=99, username="u", first_name="U", last_name=None)
    stage, changed = await JourneyEngine.classify_and_persist(
        session, client=c, recent_inbound_count=2
    )
    assert stage is Stage.WARMUP
    assert changed is True
    await session.refresh(c)
    assert c.current_stage == Stage.WARMUP.value

    # Idempotent: second call doesn't claim a change.
    _, changed2 = await JourneyEngine.classify_and_persist(
        session, client=c, recent_inbound_count=2
    )
    assert changed2 is False


async def test_offer_window_just_inside_and_outside(session) -> None:
    just_inside = NOW - OFFER_PENDING_WINDOW + timedelta(seconds=1)
    just_outside = NOW - OFFER_PENDING_WINDOW - timedelta(seconds=1)
    c1 = await _client(session, fan_id=2, last_offer_at=just_inside)
    c2 = await _client(session, fan_id=3, last_offer_at=just_outside)
    assert classify_stage(c1, recent_inbound_count=10, now=NOW) is Stage.OFFER_PENDING
    # Outside the offer window, no purchase → falls through to inbound-driven.
    assert classify_stage(c2, recent_inbound_count=10, now=NOW) is Stage.QUALIFY

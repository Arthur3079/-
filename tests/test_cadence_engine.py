"""Tests for `CadenceEngine` — sales-offer + proactive-send + reply gating."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.cadence import (
    MAX_OUTBOUND_BURST,
    MIN_INBOUND_BEFORE_OFFER,
    OFFER_COOLDOWN,
    CadenceEngine,
)
from sonya.crm.repository import get_or_create_client, update_safety_flags
from sonya.db import models  # noqa: F401
from sonya.db.base import Base
from sonya.journey import Stage


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
        session,
        fan_id=overrides.pop("fan_id", 1),
        username="u",
        first_name="U",
        last_name=None,
    )
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


NOW = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)


# ---------- should_offer_sales ----------


async def test_offer_blocked_by_safety(session) -> None:
    c = await _client(session)
    v = CadenceEngine.should_offer_sales(
        c,
        stage=Stage.QUALIFY,
        sales_allowed_by_safety=False,
        recent_inbound_count=99,
        now=NOW,
    )
    assert not v.allowed
    assert v.reason == "safety_blocks_sales"


async def test_offer_blocked_below_min_inbound(session) -> None:
    c = await _client(session)
    for n in range(MIN_INBOUND_BEFORE_OFFER):
        v = CadenceEngine.should_offer_sales(
            c,
            stage=Stage.WARMUP,
            sales_allowed_by_safety=True,
            recent_inbound_count=n,
            now=NOW,
        )
        assert not v.allowed
        assert v.reason == "below_min_inbound"


async def test_offer_allowed_at_threshold(session) -> None:
    c = await _client(session)
    v = CadenceEngine.should_offer_sales(
        c,
        stage=Stage.QUALIFY,
        sales_allowed_by_safety=True,
        recent_inbound_count=MIN_INBOUND_BEFORE_OFFER,
        now=NOW,
    )
    assert v.allowed


async def test_offer_blocked_by_cooldown(session) -> None:
    c = await _client(session, last_offer_at=NOW - timedelta(hours=1))
    v = CadenceEngine.should_offer_sales(
        c,
        stage=Stage.QUALIFY,
        sales_allowed_by_safety=True,
        recent_inbound_count=10,
        now=NOW,
    )
    assert not v.allowed
    assert v.reason == "offer_cooldown"
    assert v.metadata["seconds_until_cooldown_clears"] > 0


async def test_offer_allowed_after_cooldown(session) -> None:
    c = await _client(session, last_offer_at=NOW - OFFER_COOLDOWN - timedelta(seconds=1))
    v = CadenceEngine.should_offer_sales(
        c,
        stage=Stage.QUALIFY,
        sales_allowed_by_safety=True,
        recent_inbound_count=10,
        now=NOW,
    )
    assert v.allowed


@pytest.mark.parametrize("stage", [Stage.PAUSED_SAFETY, Stage.HANDOFF, Stage.GHOST])
async def test_offer_blocked_by_stage(session, stage: Stage) -> None:
    c = await _client(session)
    v = CadenceEngine.should_offer_sales(
        c,
        stage=stage,
        sales_allowed_by_safety=True,
        recent_inbound_count=10,
        now=NOW,
    )
    assert not v.allowed
    assert v.reason == "stage_blocks_sales"


@pytest.mark.parametrize(
    "flag", ["vulnerable", "financial_distress", "intoxication", "minors", "stop_request"]
)
async def test_offer_blocked_by_flag(session, flag: str) -> None:
    c = await _client(session, fan_id=hash(flag) % 10000)
    await update_safety_flags(session, fan_id=c.fan_id, add=[flag])
    await session.refresh(c)
    v = CadenceEngine.should_offer_sales(
        c,
        stage=Stage.QUALIFY,
        sales_allowed_by_safety=True,
        recent_inbound_count=10,
        now=NOW,
    )
    assert not v.allowed
    assert v.reason == "flag_blocks_sales"
    assert v.metadata["flag"] == flag


# ---------- should_proactively_send ----------


async def test_proactive_blocked_by_suppression(session) -> None:
    c = await _client(session, suppression_until=NOW + timedelta(hours=1))
    v = CadenceEngine.should_proactively_send(c, now=NOW)
    assert not v.allowed
    assert v.reason == "suppressed"


async def test_proactive_blocked_by_handoff(session) -> None:
    c = await _client(session, handoff_required=True)
    v = CadenceEngine.should_proactively_send(c, now=NOW)
    assert not v.allowed
    assert v.reason == "handoff_required"


async def test_proactive_blocked_by_burst_limit(session) -> None:
    c = await _client(session, consecutive_outbound_without_reply=MAX_OUTBOUND_BURST)
    v = CadenceEngine.should_proactively_send(c, now=NOW)
    assert not v.allowed
    assert v.reason == "outbound_burst_limit"


async def test_proactive_allowed_when_clean(session) -> None:
    c = await _client(session)
    v = CadenceEngine.should_proactively_send(c, now=NOW)
    assert v.allowed


async def test_proactive_blocked_by_paused_operator(session) -> None:
    c = await _client(session, is_paused=True)
    v = CadenceEngine.should_proactively_send(c, now=NOW)
    assert not v.allowed
    assert v.reason == "operator_paused"


# ---------- should_reply ----------


async def test_should_reply_blocked_by_handoff(session) -> None:
    c = await _client(session, handoff_required=True)
    v = CadenceEngine.should_reply(c, now=NOW)
    assert not v.allowed
    assert v.reason == "handoff_required"


async def test_should_reply_allowed_by_default(session) -> None:
    c = await _client(session)
    v = CadenceEngine.should_reply(c, now=NOW)
    assert v.allowed


async def test_should_reply_blocked_when_paused(session) -> None:
    c = await _client(session, is_paused=True)
    v = CadenceEngine.should_reply(c, now=NOW)
    assert not v.allowed
    assert v.reason == "operator_paused"

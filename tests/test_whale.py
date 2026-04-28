"""Tests for Phase 5: WhaleEngine — detection, promotion, retention, upsell."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.crm.repository import get_or_create_client
from sonya.crm.whale import (
    UPSELL_COOLDOWN_DAYS,
    WHALE_COLD_DAYS,
    WHALE_COOLING_DAYS,
    WHALE_GHOST_RECOVERY_HOURS,
    WHALE_MAX_OUTBOUND_BURST,
    WHALE_PURCHASES_30D,
    WHALE_SINGLE_TIP,
    WHALE_SPEND_30D,
    WhaleEngine,
)
from sonya.db import models  # noqa: F401 — register models
from sonya.db.base import Base
from sonya.db.models import Client, SaleOutcome, SalesAttempt

# ---- Fixtures ----


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        await get_or_create_client(
            s, fan_id=1, username="whale_fan", first_name="Anna", last_name=None
        )
        await get_or_create_client(
            s, fan_id=2, username="regular_fan", first_name="Bob", last_name=None
        )
        await s.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def session(session_factory):
    async with session_factory() as s:
        yield s


async def _add_purchases(
    session, fan_id: int, count: int, amount: float, days_ago: int = 0
) -> None:
    """Helper: add purchase records for a fan."""
    now = datetime.now(UTC)
    for i in range(count):
        sa = SalesAttempt(
            fan_id=fan_id,
            outcome=SaleOutcome.PURCHASED,
            attempted_at=now - timedelta(days=days_ago, hours=i),
            amount_stars=int(amount * 10),
            amount_usd_equivalent=amount,
        )
        session.add(sa)
    await session.flush()


# ---- Detection Tests ----


class TestWhaleDetection:
    async def test_detects_whale_by_spend_30d(self, session) -> None:
        client = await session.get(Client, 1)
        client.total_spend_lifetime = 400.0
        await _add_purchases(session, 1, count=5, amount=80.0, days_ago=10)
        await session.commit()

        signals = await WhaleEngine.detect_whale(session, client=client)
        assert signals.is_whale is True
        assert signals.spend_30d >= WHALE_SPEND_30D
        assert signals.confidence in ("mid", "high")

    async def test_detects_whale_by_purchase_count(self, session) -> None:
        client = await session.get(Client, 1)
        client.total_spend_lifetime = 200.0
        await _add_purchases(session, 1, count=5, amount=10.0, days_ago=5)
        await session.commit()

        signals = await WhaleEngine.detect_whale(session, client=client)
        assert signals.purchases_30d >= WHALE_PURCHASES_30D
        assert signals.is_whale is True

    async def test_detects_whale_by_single_large_tip(self, session) -> None:
        client = await session.get(Client, 1)
        client.total_spend_lifetime = 150.0
        await _add_purchases(session, 1, count=1, amount=75.0, days_ago=2)
        await session.commit()

        signals = await WhaleEngine.detect_whale(session, client=client)
        assert signals.max_single_purchase >= WHALE_SINGLE_TIP
        assert signals.is_whale is True

    async def test_not_whale_with_low_spend(self, session) -> None:
        client = await session.get(Client, 2)
        client.total_spend_lifetime = 20.0
        await session.commit()

        signals = await WhaleEngine.detect_whale(session, client=client)
        assert signals.is_whale is False

    async def test_high_confidence_when_many_signals(self, session) -> None:
        client = await session.get(Client, 1)
        client.total_spend_lifetime = 500.0
        client.first_seen = datetime.now(UTC) - timedelta(days=60)
        await _add_purchases(session, 1, count=6, amount=100.0, days_ago=10)
        await session.commit()

        signals = await WhaleEngine.detect_whale(session, client=client)
        assert signals.is_whale is True
        assert signals.confidence == "high"


# ---- Promotion Tests ----


class TestWhalePromotion:
    async def test_promotes_qualifying_fan(self, session) -> None:
        client = await session.get(Client, 1)
        client.total_spend_lifetime = 400.0
        await _add_purchases(session, 1, count=5, amount=80.0, days_ago=10)
        await session.commit()

        promoted = await WhaleEngine.maybe_promote(session, client=client)
        await session.commit()
        assert promoted is True

        updated = await session.get(Client, 1)
        assert updated.fan_type == "B1"

    async def test_no_promote_low_confidence(self, session) -> None:
        client = await session.get(Client, 2)
        client.total_spend_lifetime = 50.0
        await session.commit()

        promoted = await WhaleEngine.maybe_promote(session, client=client)
        assert promoted is False

    async def test_no_promote_already_whale(self, session) -> None:
        client = await session.get(Client, 1)
        client.fan_type = "B1"
        client.total_spend_lifetime = 500.0
        await _add_purchases(session, 1, count=5, amount=100.0, days_ago=5)
        await session.commit()

        promoted = await WhaleEngine.maybe_promote(session, client=client)
        assert promoted is False


# ---- Retention Tests ----


class TestWhaleRetention:
    def test_not_cooling_when_recent_activity(self) -> None:
        client = Client(
            fan_id=1,
            username="x",
            first_name="X",
            fan_type="B1",
            last_inbound_at=datetime.now(UTC) - timedelta(hours=12),
        )
        status = WhaleEngine.check_retention(client)
        assert status.is_cooling is False
        assert status.is_cold is False
        assert status.should_handoff is False

    def test_cooling_after_threshold(self) -> None:
        client = Client(
            fan_id=1,
            username="x",
            first_name="X",
            fan_type="B1",
            last_inbound_at=datetime.now(UTC) - timedelta(days=WHALE_COOLING_DAYS + 1),
        )
        status = WhaleEngine.check_retention(client)
        assert status.is_cooling is True
        assert status.is_cold is False

    def test_cold_after_threshold(self) -> None:
        client = Client(
            fan_id=1,
            username="x",
            first_name="X",
            fan_type="B1",
            last_inbound_at=datetime.now(UTC) - timedelta(days=WHALE_COLD_DAYS + 1),
        )
        status = WhaleEngine.check_retention(client)
        assert status.is_cold is True

    def test_handoff_when_cold_and_unresponsive(self) -> None:
        client = Client(
            fan_id=1,
            username="x",
            first_name="X",
            fan_type="B1",
            last_inbound_at=datetime.now(UTC) - timedelta(days=WHALE_COLD_DAYS + 1),
            consecutive_outbound_without_reply=4,
        )
        status = WhaleEngine.check_retention(client)
        assert status.should_handoff is True
        assert status.handoff_reason == "whale_cold_unresponsive"

    def test_no_handoff_when_cold_but_not_tried(self) -> None:
        client = Client(
            fan_id=1,
            username="x",
            first_name="X",
            fan_type="B1",
            last_inbound_at=datetime.now(UTC) - timedelta(days=WHALE_COLD_DAYS + 1),
            consecutive_outbound_without_reply=1,
        )
        status = WhaleEngine.check_retention(client)
        assert status.is_cold is True
        assert status.should_handoff is False


# ---- Upsell Tests ----


class TestWhaleUpsell:
    def test_eligible_whale_with_purchase(self) -> None:
        client = Client(
            fan_id=1,
            username="x",
            first_name="X",
            fan_type="B1",
            total_spend_lifetime=200.0,
            last_purchase_at=datetime.now(UTC) - timedelta(days=20),
            last_offer_at=datetime.now(UTC) - timedelta(days=20),
        )
        rec = WhaleEngine.recommend_upsell(client)
        assert rec.eligible is True
        assert rec.next_tier == rec.current_tier + 1

    def test_not_eligible_non_whale(self) -> None:
        client = Client(
            fan_id=1,
            username="x",
            first_name="X",
            fan_type="A1",
            total_spend_lifetime=50.0,
        )
        rec = WhaleEngine.recommend_upsell(client)
        assert rec.eligible is False
        assert rec.reason == "not_whale"

    def test_not_eligible_no_purchases(self) -> None:
        client = Client(
            fan_id=1,
            username="x",
            first_name="X",
            fan_type="B1",
            total_spend_lifetime=100.0,
        )
        rec = WhaleEngine.recommend_upsell(client)
        assert rec.eligible is False
        assert rec.reason == "no_purchases"

    def test_not_eligible_cooldown_active(self) -> None:
        client = Client(
            fan_id=1,
            username="x",
            first_name="X",
            fan_type="B1",
            total_spend_lifetime=200.0,
            last_purchase_at=datetime.now(UTC) - timedelta(days=5),
            last_offer_at=datetime.now(UTC) - timedelta(days=5),
        )
        rec = WhaleEngine.recommend_upsell(client)
        assert rec.eligible is False
        assert rec.reason == "cooldown_active"

    def test_not_eligible_max_tier(self) -> None:
        client = Client(
            fan_id=1,
            username="x",
            first_name="X",
            fan_type="B1",
            total_spend_lifetime=1500.0,
            last_purchase_at=datetime.now(UTC) - timedelta(days=20),
            last_offer_at=datetime.now(UTC) - timedelta(days=20),
        )
        rec = WhaleEngine.recommend_upsell(client)
        assert rec.eligible is False
        assert rec.reason == "max_tier_reached"


# ---- Quick check helper ----


class TestIsWhale:
    def test_b1_is_whale(self) -> None:
        client = Client(fan_id=1, username="x", first_name="X", fan_type="B1")
        assert WhaleEngine.is_whale(client) is True

    def test_whale_string_is_whale(self) -> None:
        client = Client(fan_id=1, username="x", first_name="X", fan_type="WHALE")
        assert WhaleEngine.is_whale(client) is True

    def test_regular_is_not_whale(self) -> None:
        client = Client(fan_id=1, username="x", first_name="X", fan_type="A1")
        assert WhaleEngine.is_whale(client) is False

    def test_none_is_not_whale(self) -> None:
        client = Client(fan_id=1, username="x", first_name="X", fan_type=None)
        assert WhaleEngine.is_whale(client) is False


# ---- Constants sanity ----


class TestWhaleConstants:
    def test_ghost_recovery_hours(self) -> None:
        assert WHALE_GHOST_RECOVERY_HOURS == (12, 24, 48)

    def test_max_outbound_burst(self) -> None:
        assert WHALE_MAX_OUTBOUND_BURST == 5

    def test_upsell_cooldown(self) -> None:
        assert UPSELL_COOLDOWN_DAYS == 14

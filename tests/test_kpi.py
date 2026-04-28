"""Tests for Phase 7: KPI Dashboard — metrics, fan stats, admin commands."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.admin.commands import dispatch_command
from sonya.config import Settings
from sonya.crm.repository import get_or_create_client
from sonya.db import models  # noqa: F401 — register models
from sonya.db.base import Base
from sonya.db.models import (
    Message,
    MessageDirection,
    SaleOutcome,
    SalesAttempt,
)
from sonya.kpi.metrics import (
    KPIEngine,
    render_fan_stats,
    render_global_metrics,
)


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        c1 = await get_or_create_client(
            s, fan_id=1, username="alice", first_name="Alice", last_name=None
        )
        c2 = await get_or_create_client(
            s, fan_id=2, username="bob", first_name="Bob", last_name=None
        )
        # Alice: active whale with purchases.
        c1.fan_type = "B1"
        c1.total_spend_lifetime = 500.0
        c1.first_seen = datetime.now(UTC) - timedelta(days=60)
        # Bob: regular fan.
        c2.fan_type = "A1"
        c2.total_spend_lifetime = 20.0
        c2.first_seen = datetime.now(UTC) - timedelta(days=10)

        # Add messages for Alice.
        now = datetime.now(UTC)
        for i in range(5):
            s.add(
                Message(
                    fan_id=1,
                    tg_message_id=100 + i,
                    direction=MessageDirection.INCOMING,
                    content=f"msg {i}",
                    timestamp=now - timedelta(hours=i),
                )
            )
            s.add(
                Message(
                    fan_id=1,
                    tg_message_id=200 + i,
                    direction=MessageDirection.OUTGOING,
                    content=f"reply {i}",
                    timestamp=now - timedelta(hours=i, minutes=1),
                )
            )
        # Add messages for Bob.
        for i in range(2):
            s.add(
                Message(
                    fan_id=2,
                    tg_message_id=300 + i,
                    direction=MessageDirection.INCOMING,
                    content=f"bob msg {i}",
                    timestamp=now - timedelta(hours=i),
                )
            )

        # Add purchase for Alice.
        s.add(
            SalesAttempt(
                fan_id=1,
                outcome=SaleOutcome.PURCHASED,
                attempted_at=now - timedelta(days=5),
                amount_stars=100,
                amount_usd_equivalent=50.0,
            )
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


# ---- Global metrics tests ----


class TestGlobalMetrics:
    async def test_computes_basic_metrics(self, session) -> None:
        m = await KPIEngine.global_metrics(session, window_days=30)
        assert m.total_fans == 2
        assert m.active_fans >= 1
        assert m.total_messages_in >= 5
        assert m.total_messages_out >= 5
        assert m.response_rate > 0
        assert m.total_revenue == 50.0
        assert m.total_purchases == 1
        assert m.whale_count == 1

    async def test_metrics_with_short_window(self, session) -> None:
        m = await KPIEngine.global_metrics(session, window_days=1)
        assert m.total_fans == 2
        assert m.active_fans >= 1

    async def test_render_global_metrics(self, session) -> None:
        m = await KPIEngine.global_metrics(session, window_days=30)
        text = render_global_metrics(m)
        assert "KPI Dashboard" in text
        assert "Revenue" in text
        assert "Fans" in text


# ---- Fan stats tests ----


class TestFanStats:
    async def test_fan_stats_exists(self, session) -> None:
        s = await KPIEngine.fan_stats(session, fan_id=1)
        assert s is not None
        assert s.fan_id == 1
        assert s.display_name == "Alice"
        assert s.fan_type == "B1"
        assert s.total_messages_in == 5
        assert s.total_messages_out == 5
        assert s.total_spend == 500.0
        assert s.purchase_count == 1
        assert s.days_active >= 59

    async def test_fan_stats_not_found(self, session) -> None:
        s = await KPIEngine.fan_stats(session, fan_id=9999)
        assert s is None

    async def test_render_fan_stats(self, session) -> None:
        s = await KPIEngine.fan_stats(session, fan_id=1)
        text = render_fan_stats(s)
        assert "Alice" in text
        assert "B1" in text
        assert "$500.00" in text


# ---- Top fans tests ----


class TestTopFans:
    async def test_top_by_spend(self, session) -> None:
        fans = await KPIEngine.top_fans(session, limit=10, order_by="spend")
        assert len(fans) == 2
        assert fans[0].fan_id == 1  # Alice has higher spend.
        assert fans[0].total_spend >= fans[1].total_spend

    async def test_top_by_activity(self, session) -> None:
        fans = await KPIEngine.top_fans(session, limit=10, order_by="active")
        assert len(fans) >= 1


# ---- Safety stats tests ----


class TestSafetyStats:
    async def test_empty_safety_stats(self, session) -> None:
        s = await KPIEngine.safety_stats(session, window_days=30)
        assert s.total_blocks == 0
        assert s.handoffs_triggered == 0


# ---- Admin command tests ----


class TestAdminKPICommands:
    async def test_stats_command(self, session) -> None:
        result = await dispatch_command(
            session, admin_user_id=999, raw_text="/stats", settings=Settings()
        )
        assert result.ok is True
        assert "KPI Dashboard" in result.text

    async def test_stats_command_with_days(self, session) -> None:
        result = await dispatch_command(
            session, admin_user_id=999, raw_text="/stats 7", settings=Settings()
        )
        assert result.ok is True
        assert "7 days" in result.text

    async def test_fan_command(self, session) -> None:
        result = await dispatch_command(
            session, admin_user_id=999, raw_text="/fan 1", settings=Settings()
        )
        assert result.ok is True
        assert "Alice" in result.text

    async def test_fan_command_not_found(self, session) -> None:
        result = await dispatch_command(
            session, admin_user_id=999, raw_text="/fan 9999", settings=Settings()
        )
        assert result.ok is False
        assert "not found" in result.text

    async def test_top_command(self, session) -> None:
        result = await dispatch_command(
            session, admin_user_id=999, raw_text="/top", settings=Settings()
        )
        assert result.ok is True
        assert "Top 10" in result.text
        assert "Alice" in result.text

    async def test_top_command_by_active(self, session) -> None:
        result = await dispatch_command(
            session, admin_user_id=999, raw_text="/top active", settings=Settings()
        )
        assert result.ok is True
        assert "Top 10" in result.text

    async def test_help_includes_new_commands(self, session) -> None:
        result = await dispatch_command(
            session, admin_user_id=999, raw_text="/help", settings=Settings()
        )
        assert "/stats" in result.text
        assert "/fan" in result.text
        assert "/top" in result.text

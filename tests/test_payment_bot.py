"""Tests for sonya.payment_bot.handlers (Phase 6)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.crm.repository import get_or_create_client
from sonya.db import models  # noqa: F401
from sonya.db.base import Base
from sonya.db.models import (
    Client,
    ContentDelivery,
    ContentSet,
    PaymentEvent,
    SaleOutcome,
    SalesAttempt,
)
from sonya.payment_bot.bot_api import BotApi, BotApiError
from sonya.payment_bot.handlers import (
    apply_pre_checkout,
    apply_successful_payment,
    record_invoice_event,
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        await get_or_create_client(s, fan_id=42, username="x", first_name="X", last_name=None)
        # Seed a content set + offered attempt
        cs = ContentSet(code="07", name="Test", price_stars=500, is_active=True)
        s.add(cs)
        await s.flush()
        attempt = SalesAttempt(
            fan_id=42,
            content_set_id=cs.id,
            attempted_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            outcome=SaleOutcome.SENT,
            amount_stars=500,
            invoice_payload="sonya:42:1:abcd",
        )
        s.add(attempt)
        await s.commit()
        yield s
    await engine.dispose()


async def test_record_invoice_event(session) -> None:
    ev = await record_invoice_event(
        session, fan_id=42, invoice_payload="sonya:42:1:abcd", amount_stars=500
    )
    await session.commit()
    assert ev.event_type == "invoice_created"
    assert ev.invoice_payload == "sonya:42:1:abcd"


async def test_pre_checkout_logs_event(session) -> None:
    ev = await apply_pre_checkout(
        session, fan_id=42, invoice_payload="sonya:42:1:abcd", amount_stars=500
    )
    await session.commit()
    assert ev.event_type == "pre_checkout"
    assert ev.sales_attempt_id is not None


async def test_successful_payment_marks_purchased_and_creates_delivery(session) -> None:
    applied = await apply_successful_payment(
        session,
        fan_id=42,
        invoice_payload="sonya:42:1:abcd",
        amount_stars=500,
        telegram_charge_id="TG_CHARGE_1",
    )
    await session.commit()
    assert applied.sales_attempt_id is not None
    assert applied.delivery_id is not None

    sa = (await session.execute(select(SalesAttempt))).scalar_one()
    assert sa.outcome == SaleOutcome.PURCHASED

    deliveries = (await session.execute(select(ContentDelivery))).scalars().all()
    assert len(deliveries) == 1
    assert deliveries[0].delivery_status == "pending"

    fan = (await session.execute(select(Client).where(Client.fan_id == 42))).scalar_one()
    assert fan.total_spend_lifetime == 500
    assert fan.total_spend_30d == 500
    # Layer 1: purchase resets outbound counter and stamps last_purchase_at.
    assert fan.last_purchase_at is not None
    assert fan.consecutive_outbound_without_reply == 0
    # Layer 1: an events_log row is written for the purchase.
    from sonya.db.models import EventLog

    purchase_events = (
        (await session.execute(select(EventLog).where(EventLog.event_type == "purchase_recorded")))
        .scalars()
        .all()
    )
    assert len(purchase_events) == 1
    assert purchase_events[0].fan_id == 42


async def test_successful_payment_unknown_payload_creates_event_only(session) -> None:
    applied = await apply_successful_payment(
        session,
        fan_id=42,
        invoice_payload="sonya:42:99:nope",
        amount_stars=200,
    )
    await session.commit()
    assert applied.sales_attempt_id is None
    assert applied.delivery_id is None

    events = (await session.execute(select(PaymentEvent))).scalars().all()
    assert any(e.event_type == "successful" for e in events)


def test_bot_api_requires_token() -> None:
    with pytest.raises(ValueError):
        BotApi("")


def test_bot_api_error_str() -> None:
    e = BotApiError("sendInvoice", 400, "Bad Request")
    assert "sendInvoice" in str(e)
    assert "Bad Request" in str(e)
    assert e.code == 400

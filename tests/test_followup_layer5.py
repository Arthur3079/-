"""Layer 5 tests: auto-aftercare, pre-send cadence re-check, idempotent enqueue,
and stop-request cancelling pending followups.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.crm.repository import (
    get_or_create_client,
    set_handoff_required,
    set_suppression_for,
)
from sonya.db import models  # noqa: F401
from sonya.db.base import Base
from sonya.db.models import (
    ContentSet,
    EventLog,
    Followup,
    SaleOutcome,
    SalesAttempt,
)
from sonya.payment_bot.handlers import apply_successful_payment
from sonya.safety import SafetyEngine
from sonya.scheduler.repository import (
    cancel_pending_for_fan,
    enqueue_followup,
    list_pending,
)
from sonya.scheduler.service import CadenceConfig, SchedulerService


@pytest.fixture
async def engine_and_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield engine, factory
    await engine.dispose()


@pytest.fixture
async def session(engine_and_factory):
    _engine, factory = engine_and_factory
    async with factory() as s:
        yield s


# ---------- idempotent enqueue ----------


async def test_enqueue_idempotent_returns_existing(session) -> None:
    await get_or_create_client(session, fan_id=1, username="u", first_name="U", last_name=None)
    when = datetime.now(UTC) + timedelta(hours=24)
    a = await enqueue_followup(session, fan_id=1, type_="aftercare_thanks", scheduled_at=when)
    b = await enqueue_followup(
        session, fan_id=1, type_="aftercare_thanks", scheduled_at=when + timedelta(hours=2)
    )
    assert a.id == b.id  # same row reused
    rows = (await session.execute(select(Followup).where(Followup.fan_id == 1))).scalars().all()
    assert len(rows) == 1


async def test_enqueue_idempotent_pulls_in_earlier_time(session) -> None:
    await get_or_create_client(session, fan_id=2, username="u", first_name="U", last_name=None)
    later = datetime.now(UTC) + timedelta(hours=24)
    earlier = datetime.now(UTC) + timedelta(hours=1)
    a = await enqueue_followup(session, fan_id=2, type_="aftercare_thanks", scheduled_at=later)
    b = await enqueue_followup(session, fan_id=2, type_="aftercare_thanks", scheduled_at=earlier)
    assert a.id == b.id
    await session.refresh(a)
    stored = a.scheduled_at
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=UTC)
    assert abs((stored - earlier).total_seconds()) < 1


async def test_enqueue_non_idempotent_creates_duplicate(session) -> None:
    await get_or_create_client(session, fan_id=3, username="u", first_name="U", last_name=None)
    when = datetime.now(UTC) + timedelta(hours=24)
    a = await enqueue_followup(
        session, fan_id=3, type_="custom", scheduled_at=when, idempotent=False
    )
    b = await enqueue_followup(
        session, fan_id=3, type_="custom", scheduled_at=when, idempotent=False
    )
    assert a.id != b.id


# ---------- auto-aftercare on successful payment ----------


async def test_successful_payment_enqueues_aftercare(session) -> None:
    await get_or_create_client(session, fan_id=42, username="x", first_name="X", last_name=None)
    cs = ContentSet(code="07", name="Test", price_stars=500, is_active=True)
    session.add(cs)
    await session.flush()
    session.add(
        SalesAttempt(
            fan_id=42,
            content_set_id=cs.id,
            attempted_at=datetime.now(UTC),
            outcome=SaleOutcome.SENT,
            amount_stars=500,
            invoice_payload="sonya:42:1:p",
        )
    )
    await session.commit()

    await apply_successful_payment(
        session,
        fan_id=42,
        invoice_payload="sonya:42:1:p",
        amount_stars=500,
    )
    await session.commit()

    pending = await list_pending(session, fan_id=42)
    types = sorted(p.type for p in pending)
    assert types == ["aftercare_checkin", "aftercare_thanks"]


async def test_successful_payment_idempotent_does_not_double_enqueue(session) -> None:
    await get_or_create_client(session, fan_id=43, username="x", first_name="X", last_name=None)
    cs = ContentSet(code="07", name="Test", price_stars=500, is_active=True)
    session.add(cs)
    await session.flush()
    session.add(
        SalesAttempt(
            fan_id=43,
            content_set_id=cs.id,
            attempted_at=datetime.now(UTC),
            outcome=SaleOutcome.SENT,
            amount_stars=500,
            invoice_payload="sonya:43:1:p",
        )
    )
    await session.commit()

    for _ in range(3):  # webhook fires three times
        await apply_successful_payment(
            session,
            fan_id=43,
            invoice_payload="sonya:43:1:p",
            amount_stars=500,
        )
    await session.commit()

    pending = await list_pending(session, fan_id=43)
    assert len(pending) == 2  # aftercare_thanks + aftercare_checkin only


# ---------- stop_request cancels pending followups ----------


async def test_stop_request_cancels_pending_followups(session) -> None:
    client = await get_or_create_client(
        session, fan_id=50, username="x", first_name="X", last_name=None
    )
    when = datetime.now(UTC) + timedelta(hours=24)
    await enqueue_followup(session, fan_id=50, type_="aftercare_thanks", scheduled_at=when)
    await enqueue_followup(
        session, fan_id=50, type_="aftercare_checkin", scheduled_at=when + timedelta(days=2)
    )
    pending_before = await list_pending(session, fan_id=50)
    assert len(pending_before) == 2

    await SafetyEngine.precheck(session, client=client, text="leave me alone please")

    pending_after = await list_pending(session, fan_id=50)
    assert pending_after == []
    # Cancellation reason recorded.
    cancelled = (
        (await session.execute(select(Followup).where(Followup.fan_id == 50))).scalars().all()
    )
    assert all(f.cancelled for f in cancelled)
    assert all("suppression:" in (f.note or "") for f in cancelled)


async def test_handoff_cancels_pending_followups(session) -> None:
    client = await get_or_create_client(
        session, fan_id=51, username="x", first_name="X", last_name=None
    )
    when = datetime.now(UTC) + timedelta(hours=24)
    await enqueue_followup(session, fan_id=51, type_="aftercare_thanks", scheduled_at=when)

    await SafetyEngine.precheck(session, client=client, text="i'm 15 btw")

    pending = await list_pending(session, fan_id=51)
    assert pending == []


# ---------- pre-send cadence re-check ----------


async def test_dispatch_skips_when_suppressed(session, engine_and_factory) -> None:
    _engine, factory = engine_and_factory
    sent: list[tuple[int, str, str]] = []

    async def fake_send(fan_id: int, text: str, type_: str) -> bool:
        sent.append((fan_id, text, type_))
        return True

    svc = SchedulerService(
        session_factory=factory,
        send=fake_send,
        config=CadenceConfig(tick_interval_seconds=999.0),
    )

    await get_or_create_client(session, fan_id=60, username="x", first_name="X", last_name=None)
    past = datetime.now(UTC) - timedelta(seconds=1)
    await enqueue_followup(session, fan_id=60, type_="aftercare_thanks", scheduled_at=past)
    # Suppress the fan AFTER enqueue (simulates a stop_request between
    # enqueue and dispatch).
    await set_suppression_for(session, fan_id=60, hours=1)
    await session.commit()

    n = await svc.run_once()
    assert n == 0  # nothing actually sent
    assert sent == []

    # Followup row is now cancelled (not executed) with the cadence reason.
    row = (await session.execute(select(Followup).where(Followup.fan_id == 60))).scalar_one()
    assert row.cancelled is True
    assert "suppressed" in (row.note or "")

    # An events_log row was emitted.
    skip_events = (
        (
            await session.execute(
                select(EventLog).where(
                    EventLog.fan_id == 60, EventLog.event_type == "followup_skipped"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(skip_events) == 1


async def test_dispatch_skips_when_handoff(session, engine_and_factory) -> None:
    _engine, factory = engine_and_factory

    async def fake_send(fan_id: int, text: str, type_: str) -> bool:
        return True

    svc = SchedulerService(
        session_factory=factory,
        send=fake_send,
        config=CadenceConfig(tick_interval_seconds=999.0),
    )

    await get_or_create_client(session, fan_id=61, username="x", first_name="X", last_name=None)
    past = datetime.now(UTC) - timedelta(seconds=1)
    await enqueue_followup(session, fan_id=61, type_="ghost_recovery", scheduled_at=past)
    await set_handoff_required(session, fan_id=61, reason="manual")
    await session.commit()

    n = await svc.run_once()
    assert n == 0


async def test_dispatch_sends_when_clean(session, engine_and_factory) -> None:
    _engine, factory = engine_and_factory
    sent: list[tuple[int, str, str]] = []

    async def fake_send(fan_id: int, text: str, type_: str) -> bool:
        sent.append((fan_id, text, type_))
        return True

    svc = SchedulerService(
        session_factory=factory,
        send=fake_send,
        config=CadenceConfig(tick_interval_seconds=999.0),
    )

    await get_or_create_client(session, fan_id=62, username="x", first_name="X", last_name=None)
    past = datetime.now(UTC) - timedelta(seconds=1)
    await enqueue_followup(session, fan_id=62, type_="aftercare_thanks", scheduled_at=past)
    await session.commit()

    n = await svc.run_once()
    assert n == 1
    assert sent and sent[0][0] == 62 and sent[0][2] == "aftercare_thanks"


# ---------- cancel_pending_for_fan + write_event interplay ----------


async def test_cancel_pending_for_fan_returns_count(session) -> None:
    await get_or_create_client(session, fan_id=70, username="x", first_name="X", last_name=None)
    when = datetime.now(UTC) + timedelta(hours=24)
    await enqueue_followup(session, fan_id=70, type_="t1", scheduled_at=when)
    await enqueue_followup(session, fan_id=70, type_="t2", scheduled_at=when)
    n = await cancel_pending_for_fan(session, fan_id=70, reason="test")
    assert n == 2
    pending = await list_pending(session, fan_id=70)
    assert pending == []

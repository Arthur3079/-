"""Tests for cadence engine + SchedulerService (Phase 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.crm.repository import get_or_create_client
from sonya.db import models  # noqa: F401
from sonya.db.base import Base
from sonya.db.models import Followup
from sonya.scheduler import (
    SchedulerService,
    build_followup_message,
    cancel_pending_for_fan,
    due_followups,
    enqueue_followup,
    list_pending,
    mark_executed,
)
from sonya.scheduler.service import CadenceConfig


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        await get_or_create_client(s, fan_id=1, username="x", first_name="X", last_name=None)
        await get_or_create_client(s, fan_id=2, username="y", first_name="Y", last_name=None)
        await s.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def session(session_factory):
    async with session_factory() as s:
        yield s


async def test_enqueue_and_list_pending(session) -> None:
    when = datetime.now(UTC) + timedelta(hours=1)
    row = await enqueue_followup(session, fan_id=1, type_="ghost_recovery", scheduled_at=when)
    await session.commit()
    assert row.id is not None
    pending = await list_pending(session, fan_id=1)
    assert len(pending) == 1
    assert pending[0].type == "ghost_recovery"


async def test_due_followups_only_returns_past(session) -> None:
    now = datetime.now(UTC)
    await enqueue_followup(
        session, fan_id=1, type_="aftercare_thanks", scheduled_at=now - timedelta(minutes=5)
    )
    await enqueue_followup(
        session, fan_id=1, type_="aftercare_checkin", scheduled_at=now + timedelta(hours=1)
    )
    await session.commit()
    due = await due_followups(session, now=now)
    assert len(due) == 1
    assert due[0].type == "aftercare_thanks"


async def test_mark_executed_makes_it_no_longer_due(session) -> None:
    now = datetime.now(UTC)
    row = await enqueue_followup(
        session, fan_id=1, type_="x", scheduled_at=now - timedelta(minutes=1)
    )
    await session.commit()
    await mark_executed(session, followup_id=row.id)
    await session.commit()
    due = await due_followups(session, now=now)
    assert due == []


async def test_cancel_pending_for_fan_marks_all(session) -> None:
    now = datetime.now(UTC)
    await enqueue_followup(session, fan_id=1, type_="a", scheduled_at=now + timedelta(hours=1))
    await enqueue_followup(session, fan_id=1, type_="b", scheduled_at=now + timedelta(hours=2))
    await enqueue_followup(session, fan_id=2, type_="a", scheduled_at=now + timedelta(hours=1))
    await session.commit()
    cancelled = await cancel_pending_for_fan(session, fan_id=1, reason="replied")
    assert cancelled == 2
    await session.commit()

    rows = (await session.execute(select(Followup))).scalars().all()
    by_fan = {r.fan_id: r for r in rows if r.fan_id == 1}
    for r in rows:
        if r.fan_id == 1:
            assert r.cancelled is True
            assert r.note and "cancelled:replied" in r.note
        else:
            assert r.cancelled is False
    assert by_fan  # used


async def test_cancel_returns_zero_when_nothing_pending(session) -> None:
    out = await cancel_pending_for_fan(session, fan_id=1)
    assert out == 0


async def test_build_followup_message_variants() -> None:
    g = build_followup_message(fan_type=None, type_="ghost_recovery", name=None)
    assert "Hey," in g or "Hey " in g
    w = build_followup_message(fan_type="WHALE", type_="ghost_recovery", name="Anna")
    assert "Anna" in w
    a = build_followup_message(fan_type=None, type_="aftercare_thanks", name="Tom")
    assert "Tom" in a and "thank" in a.lower()
    bd = build_followup_message(fan_type=None, type_="birthday", name=None)
    assert "birthday" in bd.lower()
    fb = build_followup_message(fan_type=None, type_="weird_unknown_type", name=None)
    assert fb  # falls back to safe default


async def test_run_once_dispatches_due_jobs(session_factory) -> None:
    sent: list[tuple[int, str, str]] = []

    async def fake_send(fan_id: int, text: str, type_: str) -> bool:
        sent.append((fan_id, text, type_))
        return True

    async with session_factory() as s:
        await enqueue_followup(
            s,
            fan_id=1,
            type_="ghost_recovery",
            scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        await s.commit()

    svc = SchedulerService(session_factory=session_factory, send=fake_send)
    n = await svc.run_once()
    assert n == 1
    assert sent and sent[0][0] == 1


async def test_run_once_skips_paused_fan(session_factory) -> None:
    sent: list[tuple[int, str, str]] = []

    async def fake_send(fan_id: int, text: str, type_: str) -> bool:
        sent.append((fan_id, text, type_))
        return True

    async with session_factory() as s:
        await enqueue_followup(
            s,
            fan_id=1,
            type_="ghost_recovery",
            scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        client = await s.get(models.Client, 1)
        client.is_paused = True
        await s.commit()

    svc = SchedulerService(session_factory=session_factory, send=fake_send)
    n = await svc.run_once()
    # Paused fan: marked executed (we're not delivering) but don't count as sent.
    assert n == 0
    assert sent == []


async def test_failing_send_does_not_mark_executed(session_factory) -> None:
    async def boom(fan_id: int, text: str, type_: str) -> bool:
        raise RuntimeError("network fail")

    async with session_factory() as s:
        await enqueue_followup(
            s,
            fan_id=1,
            type_="ghost_recovery",
            scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        await s.commit()

    svc = SchedulerService(session_factory=session_factory, send=boom)
    n = await svc.run_once()
    assert n == 0

    async with session_factory() as s:
        rows = (await s.execute(select(Followup))).scalars().all()
        assert rows[0].executed_at is None
        assert rows[0].cancelled is False


async def test_enqueue_helpers_use_config(session_factory) -> None:
    cfg = CadenceConfig(
        ghost_recovery_after=timedelta(days=3),
        aftercare_thanks_after=timedelta(hours=1),
        aftercare_checkin_after=timedelta(days=2),
    )

    async def noop(fan_id, text, type_):  # type: ignore[no-untyped-def]
        return True

    svc = SchedulerService(session_factory=session_factory, send=noop, config=cfg)
    async with session_factory() as s:
        ghost = await svc.enqueue_ghost_recovery(s, fan_id=1)
        aftercare_rows = await svc.enqueue_aftercare(s, fan_id=2)
        await s.commit()

    delta = ghost.scheduled_at - datetime.now(UTC)
    assert timedelta(days=2, hours=23) < delta < timedelta(days=3, hours=1)
    assert len(aftercare_rows) == 2

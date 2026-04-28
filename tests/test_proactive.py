"""Tests for Phase 3: ProactiveEngine, timer matrix, timezone gate, drip sequences."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.crm.repository import get_or_create_client
from sonya.db import models  # noqa: F401 — register models
from sonya.db.base import Base
from sonya.db.models import Client
from sonya.scheduler import (
    SchedulerService,
    get_timer_for_attempt,
    get_timers,
    is_in_send_window,
)
from sonya.scheduler.proactive import ProactiveEngine
from sonya.scheduler.timer_matrix import (
    GHOST_RECOVERY_SEQUENCE,
    TIMER_MATRIX,
    WELCOME_DRIP_SEQUENCE,
    TimerRule,
)

# ---- Fixtures ----


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        await get_or_create_client(
            s, fan_id=1, username="alice", first_name="Alice", last_name=None
        )
        await get_or_create_client(s, fan_id=2, username="bob", first_name="Bob", last_name=None)
        await s.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def session(session_factory):
    async with session_factory() as s:
        yield s


# ---- Timer Matrix Tests ----


class TestTimerMatrix:
    def test_matrix_has_welcome_stage(self) -> None:
        assert "S1_WELCOME" in TIMER_MATRIX
        timers = TIMER_MATRIX["S1_WELCOME"]
        assert len(timers) == 2  # welcome drip D1 + D3

    def test_matrix_has_ghost_stage(self) -> None:
        assert "S9_GHOST_NEW" in TIMER_MATRIX
        timers = TIMER_MATRIX["S9_GHOST_NEW"]
        assert len(timers) == 3  # D1, D2, D3

    def test_ghost_sequence_intervals(self) -> None:
        assert GHOST_RECOVERY_SEQUENCE[0].after == timedelta(hours=24)
        assert GHOST_RECOVERY_SEQUENCE[1].after == timedelta(hours=48)
        assert GHOST_RECOVERY_SEQUENCE[2].after == timedelta(hours=72)

    def test_welcome_drip_intervals(self) -> None:
        assert WELCOME_DRIP_SEQUENCE[0].after == timedelta(hours=24)
        assert WELCOME_DRIP_SEQUENCE[1].after == timedelta(hours=72)

    def test_get_timers_returns_tuple(self) -> None:
        timers = get_timers("S1_WELCOME")
        assert isinstance(timers, tuple)
        assert all(isinstance(r, TimerRule) for r in timers)

    def test_get_timers_unknown_stage_returns_empty(self) -> None:
        assert get_timers("S_DOES_NOT_EXIST") == ()

    def test_get_timer_for_attempt_valid(self) -> None:
        rule = get_timer_for_attempt("S9_GHOST_NEW", attempt=0)
        assert rule is not None
        assert "D1" in rule.action

    def test_get_timer_for_attempt_exhausted(self) -> None:
        assert get_timer_for_attempt("S9_GHOST_NEW", attempt=5) is None

    def test_library_stages_with_timers_are_in_matrix(self) -> None:
        # Every stage that has timers in the JSON should be in our matrix.
        from sonya.library import LIBRARY

        for stage in LIBRARY.master_stages:
            if stage.timers and stage.id not in ("S1_WELCOME", "S9_GHOST_NEW"):
                assert stage.id in TIMER_MATRIX, f"Missing: {stage.id}"


class TestSendWindow:
    def test_within_window(self) -> None:
        assert is_in_send_window(9) is True
        assert is_in_send_window(14) is True
        assert is_in_send_window(21) is True

    def test_outside_window(self) -> None:
        assert is_in_send_window(3) is False
        assert is_in_send_window(8) is False
        assert is_in_send_window(22) is False
        assert is_in_send_window(23) is False

    def test_none_defaults_to_true(self) -> None:
        assert is_in_send_window(None) is True


# ---- ProactiveEngine Tests ----


class TestProactiveEngineStageTransition:
    async def test_enqueues_followups_on_ghost_transition(self, session) -> None:
        client = await session.get(Client, 1)
        rows = await ProactiveEngine.on_stage_transition(
            session, client=client, new_stage="ghost", old_stage="warmup"
        )
        await session.commit()
        # "ghost" maps to S9_GHOST_NEW → 3 followups (D1, D2, D3).
        assert len(rows) == 3
        types = [r.type for r in rows]
        assert "ghost_recovery_D1" in types
        assert "ghost_recovery_D2" in types
        assert "ghost_recovery_D3" in types

    async def test_enqueues_followups_on_welcome(self, session) -> None:
        client = await session.get(Client, 1)
        rows = await ProactiveEngine.on_stage_transition(
            session, client=client, new_stage="welcome"
        )
        await session.commit()
        assert len(rows) == 2
        types = [r.type for r in rows]
        assert "welcome_drip_D1" in types
        assert "welcome_drip_D3" in types

    async def test_cancels_old_followups_on_transition(self, session) -> None:
        from sonya.scheduler.repository import enqueue_followup, list_pending

        client = await session.get(Client, 1)
        # Pre-enqueue something.
        await enqueue_followup(
            session,
            fan_id=1,
            type_="ghost_recovery_D1",
            scheduled_at=datetime.now(UTC) + timedelta(hours=10),
        )
        await session.commit()
        pending = await list_pending(session, fan_id=1)
        assert len(pending) == 1

        # Transition → old followups cancelled.
        await ProactiveEngine.on_stage_transition(
            session, client=client, new_stage="warmup", old_stage="ghost"
        )
        await session.commit()
        pending = await list_pending(session, fan_id=1)
        # "warmup" has no rail timers → all old cancelled, nothing new.
        # (warmup maps to S3_WARMUP_Q which has timers in the library)
        # Actually warmup→S3_WARMUP_Q has a timer. Let's just check old one is gone.
        old_types = [r.type for r in pending]
        assert "ghost_recovery_D1" not in old_types

    async def test_no_enqueue_for_unknown_stage(self, session) -> None:
        client = await session.get(Client, 1)
        rows = await ProactiveEngine.on_stage_transition(
            session, client=client, new_stage="handoff"
        )
        await session.commit()
        assert rows == []


class TestProactiveEngineFanReplied:
    async def test_cancels_pending_followups(self, session) -> None:
        from sonya.scheduler.repository import enqueue_followup, list_pending

        await enqueue_followup(
            session,
            fan_id=1,
            type_="ghost_recovery_D1",
            scheduled_at=datetime.now(UTC) + timedelta(hours=10),
        )
        await enqueue_followup(
            session,
            fan_id=1,
            type_="ghost_recovery_D2",
            scheduled_at=datetime.now(UTC) + timedelta(hours=20),
        )
        await session.commit()

        cancelled = await ProactiveEngine.on_fan_replied(session, fan_id=1)
        await session.commit()
        assert cancelled == 2
        assert await list_pending(session, fan_id=1) == []


class TestProactiveEngineShouldSendNow:
    def test_allowed_for_normal_client(self) -> None:
        client = Client(fan_id=99, username="x", first_name="X")
        allowed, reason = ProactiveEngine.should_send_now(client)
        assert allowed is True
        assert reason == ""

    def test_blocked_when_paused(self) -> None:
        client = Client(fan_id=99, username="x", first_name="X", is_paused=True)
        allowed, reason = ProactiveEngine.should_send_now(client)
        assert allowed is False
        assert "operator_paused" in reason

    def test_blocked_when_handoff(self) -> None:
        client = Client(fan_id=99, username="x", first_name="X", handoff_required=True)
        allowed, reason = ProactiveEngine.should_send_now(client)
        assert allowed is False
        assert "handoff" in reason

    def test_blocked_when_suppressed(self) -> None:
        client = Client(
            fan_id=99,
            username="x",
            first_name="X",
            suppression_until=datetime.now(UTC) + timedelta(hours=5),
        )
        allowed, reason = ProactiveEngine.should_send_now(client)
        assert allowed is False
        assert "suppressed" in reason

    def test_blocked_when_burst_limit(self) -> None:
        client = Client(
            fan_id=99,
            username="x",
            first_name="X",
            consecutive_outbound_without_reply=5,
        )
        allowed, reason = ProactiveEngine.should_send_now(client)
        assert allowed is False
        assert "burst" in reason


class TestProactiveEngineBuildText:
    def test_ghost_recovery_d1_russian(self) -> None:
        client = Client(fan_id=1, username="x", first_name="Вася", timezone_guess=None)
        text = ProactiveEngine.build_proactive_text(
            client=client, followup_type="ghost_recovery_D1"
        )
        assert "Вася" in text
        assert len(text) > 5

    def test_ghost_recovery_whale(self) -> None:
        client = Client(fan_id=1, username="x", first_name="Anna", fan_type="B1")
        text = ProactiveEngine.build_proactive_text(
            client=client, followup_type="ghost_recovery_D1"
        )
        assert "Anna" in text

    def test_welcome_drip_d1(self) -> None:
        client = Client(fan_id=1, username="x", first_name="Max")
        text = ProactiveEngine.build_proactive_text(client=client, followup_type="welcome_drip_D1")
        assert "Max" in text
        assert len(text) > 5

    def test_aftercare_thanks(self) -> None:
        client = Client(fan_id=1, username="x", first_name="Tom")
        text = ProactiveEngine.build_proactive_text(client=client, followup_type="aftercare_thanks")
        assert "Tom" in text

    def test_unknown_type_fallback(self) -> None:
        client = Client(fan_id=1, username="x", first_name="Sam")
        text = ProactiveEngine.build_proactive_text(
            client=client, followup_type="totally_unknown_xyz"
        )
        assert "Sam" in text


# ---- Integration: SchedulerService + ProactiveEngine ----


class TestSchedulerServicePhase3:
    async def test_dispatch_uses_proactive_gate(self, session_factory) -> None:
        """Paused fan: followup gets cancelled, not sent."""
        sent: list[tuple[int, str, str]] = []

        async def fake_send(fan_id: int, text: str, type_: str) -> bool:
            sent.append((fan_id, text, type_))
            return True

        async with session_factory() as s:
            from sonya.scheduler.repository import enqueue_followup

            await enqueue_followup(
                s,
                fan_id=1,
                type_="ghost_recovery_D1",
                scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
            )
            client = await s.get(Client, 1)
            client.is_paused = True
            await s.commit()

        svc = SchedulerService(session_factory=session_factory, send=fake_send)
        n = await svc.run_once()
        assert n == 0
        assert sent == []

    async def test_dispatch_sends_grain_aware_message(self, session_factory) -> None:
        """Normal fan: followup dispatched with grain-aware text."""
        sent: list[tuple[int, str, str]] = []

        async def fake_send(fan_id: int, text: str, type_: str) -> bool:
            sent.append((fan_id, text, type_))
            return True

        async with session_factory() as s:
            from sonya.scheduler.repository import enqueue_followup

            await enqueue_followup(
                s,
                fan_id=1,
                type_="ghost_recovery_D1",
                scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
                note="stage=ghost attempt=0 template_ref=warmup.D1_check_in",
            )
            await s.commit()

        svc = SchedulerService(session_factory=session_factory, send=fake_send)
        n = await svc.run_once()
        assert n == 1
        assert sent
        assert sent[0][0] == 1
        assert len(sent[0][1]) > 5  # non-trivial text

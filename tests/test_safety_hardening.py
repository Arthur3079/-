"""Tests for Phase 6: Safety Hardening — regen loop, escalation, rate limiter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.crm.repository import get_or_create_client
from sonya.db import models  # noqa: F401 — register models
from sonya.db.base import Base
from sonya.db.models import Client, EventLog, Message, MessageDirection
from sonya.observability import EventType, write_event
from sonya.safety.hardening import (
    MAX_REGEN_ATTEMPTS,
    RATE_LIMIT_HARD_MAX_MESSAGES,
    RATE_LIMIT_MAX_MESSAGES,
    SafetyHardening,
)


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        await get_or_create_client(
            s, fan_id=1, username="test_fan", first_name="Alice", last_name=None
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


# ---- Regen nudge tests ----


class TestRegenNudge:
    def test_builds_nudge_with_reasons(self) -> None:
        nudge = SafetyHardening.build_regen_nudge(("parasocial_trap", "emoji_burst"))
        assert "parasocial_trap" in nudge
        assert "emoji_burst" in nudge
        assert "safety filter" in nudge

    def test_builds_nudge_empty_reasons(self) -> None:
        nudge = SafetyHardening.build_regen_nudge(())
        assert "safety policy violation" in nudge

    def test_max_regen_attempts_constant(self) -> None:
        assert MAX_REGEN_ATTEMPTS == 3


# ---- Escalation tests ----


class TestEscalation:
    async def test_no_escalation_below_threshold(self, session) -> None:
        client = await session.get(Client, 1)
        check = await SafetyHardening.check_escalation(
            session, client=client, current_flags=("ai_disclosure_probe",)
        )
        assert check.should_escalate is False
        assert "below_threshold" in check.reason

    async def test_escalation_after_threshold(self, session) -> None:
        client = await session.get(Client, 1)
        now = datetime.now(UTC)

        # Add enough safety events to trigger escalation.
        for _i in range(4):
            await write_event(
                session,
                fan_id=1,
                event_type=EventType.SAFETY_FLAGGED,
                payload={"flags": ["ai_disclosure_probe"], "stage": "pre"},
            )
        await session.flush()

        check = await SafetyHardening.check_escalation(
            session, client=client, current_flags=("ai_disclosure_probe",), now=now
        )
        assert check.should_escalate is True
        assert check.trigger_count >= 3

    async def test_escalation_critical_category_low_threshold(self, session) -> None:
        client = await session.get(Client, 1)
        # non_consent has threshold=1.
        await write_event(
            session,
            fan_id=1,
            event_type=EventType.SAFETY_FLAGGED,
            payload={"flags": ["non_consent"]},
        )
        await session.flush()

        check = await SafetyHardening.check_escalation(
            session, client=client, current_flags=("non_consent",)
        )
        assert check.should_escalate is True
        assert check.threshold == 1

    async def test_maybe_escalate_applies_handoff(self, session) -> None:
        client = await session.get(Client, 1)
        # Add events to exceed threshold.
        for _ in range(4):
            await write_event(
                session,
                fan_id=1,
                event_type=EventType.SAFETY_FLAGGED,
                payload={"flags": ["harassment"]},
            )
        await session.flush()

        escalated = await SafetyHardening.maybe_escalate_and_handoff(
            session, client=client, current_flags=("harassment",)
        )
        await session.commit()
        assert escalated is True

        updated = await session.get(Client, 1)
        assert updated.handoff_required is True

    async def test_maybe_escalate_no_double_handoff(self, session) -> None:
        client = await session.get(Client, 1)
        client.handoff_required = True
        await session.flush()

        for _ in range(4):
            await write_event(
                session,
                fan_id=1,
                event_type=EventType.SAFETY_FLAGGED,
                payload={"flags": ["harassment"]},
            )
        await session.flush()

        escalated = await SafetyHardening.maybe_escalate_and_handoff(
            session, client=client, current_flags=("harassment",)
        )
        assert escalated is False


# ---- Rate limiter tests ----


class TestRateLimiter:
    async def test_no_limit_few_messages(self, session) -> None:
        client = await session.get(Client, 1)
        check = await SafetyHardening.check_rate_limit(session, client=client)
        assert check.is_limited is False
        assert check.reason == "ok"

    async def test_soft_limit_triggered(self, session) -> None:
        client = await session.get(Client, 1)
        now = datetime.now(UTC)
        # Add many messages in the last 60s.
        for i in range(RATE_LIMIT_MAX_MESSAGES + 1):
            msg = Message(
                fan_id=1,
                tg_message_id=1000 + i,
                direction=MessageDirection.INCOMING,
                content=f"spam {i}",
                timestamp=now - timedelta(seconds=30 - i),
            )
            session.add(msg)
        await session.flush()

        check = await SafetyHardening.check_rate_limit(session, client=client, now=now)
        assert check.is_limited is True
        assert check.is_hard_limited is False
        assert "soft_rate_limit" in check.reason

    async def test_hard_limit_triggered(self, session) -> None:
        client = await session.get(Client, 1)
        now = datetime.now(UTC)
        # Add messages exceeding hard limit in 5min window.
        for i in range(RATE_LIMIT_HARD_MAX_MESSAGES + 1):
            msg = Message(
                fan_id=1,
                tg_message_id=2000 + i,
                direction=MessageDirection.INCOMING,
                content=f"spam hard {i}",
                timestamp=now - timedelta(seconds=200 - i),
            )
            session.add(msg)
        await session.flush()

        check = await SafetyHardening.check_rate_limit(session, client=client, now=now)
        assert check.is_limited is True
        assert check.is_hard_limited is True
        assert "hard_rate_limit" in check.reason


# ---- Audit tests ----


class TestAudit:
    async def test_record_safety_audit(self, session) -> None:
        await SafetyHardening.record_safety_audit(
            session,
            fan_id=1,
            stage="pre",
            action="replace_with_safe_reply",
            severity="medium",
            flags=("off_platform", "phone_number"),
            details={"candidate_len": 500},
        )
        await session.flush()

        from sqlalchemy import select

        stmt = select(EventLog).where(
            EventLog.fan_id == 1,
            EventLog.event_type == EventType.SAFETY_FLAGGED.value,
        )
        rows = (await session.execute(stmt)).scalars().all()
        assert len(rows) >= 1


# ---- Integration: regen in DialogueService ----


class TestRegenLoop:
    async def test_regen_succeeds_on_second_attempt(self, session) -> None:
        """Simulate a regen where the second call produces a clean reply."""
        from unittest.mock import AsyncMock

        from sonya.config import Settings
        from sonya.dialogue.service import DialogueService

        call_count = 0

        async def mock_generate(messages, *, fan_id):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # First two calls produce a bad reply (will fail evaluate_reply
                # due to phone number).
                return "hey call me at +1234567890123"
            return "привет, как дела?"

        backend = AsyncMock()
        backend.generate = mock_generate

        settings = Settings()
        service = DialogueService(settings=settings, backend=backend)

        client = await session.get(Client, 1)
        client.language = "ru"
        await session.flush()

        from sonya.dialogue.intent import Intent

        result = await service._regenerate_loop(
            session,
            client=client,
            text="hey",
            intent=Intent.SMALLTALK,
            fan_type="regular",
            blocked_reasons=("off_platform",),
        )
        # The third call should produce a clean reply.
        assert result == "привет, как дела?"

    async def test_regen_exhausted_returns_none(self, session) -> None:
        """When all regen attempts fail, return None."""
        from unittest.mock import AsyncMock

        from sonya.config import Settings
        from sonya.dialogue.service import DialogueService

        async def mock_generate(messages, *, fan_id):
            return "hey call me at +1234567890123"

        backend = AsyncMock()
        backend.generate = mock_generate

        settings = Settings()
        service = DialogueService(settings=settings, backend=backend)

        client = await session.get(Client, 1)
        await session.flush()

        from sonya.dialogue.intent import Intent

        result = await service._regenerate_loop(
            session,
            client=client,
            text="hey",
            intent=Intent.SMALLTALK,
            fan_type="regular",
            blocked_reasons=("off_platform",),
        )
        assert result is None

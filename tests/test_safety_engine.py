"""Layer 2 tests: SafetyEngine + new triggers (stop / harassment / chargeback / intox).

Two layers of test:
1. Pure regex tests on `evaluate_incoming` for the new categories.
2. `SafetyEngine.precheck` integration tests asserting the verdict is
   persisted (flags, risk_level, suppression, handoff) and an event row
   is written.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.crm.repository import get_or_create_client, update_safety_flags
from sonya.db import models  # noqa: F401  registers tables on metadata
from sonya.db.base import Base
from sonya.db.models import EventLog
from sonya.journey import RiskLevel
from sonya.safety import (
    SafetyAction,
    SafetyEngine,
    SafetySeverity,
    evaluate_incoming,
    evaluate_reply,
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


# ---------- Pure regex: stop_request ----------


class TestStopRequestPatterns:
    @pytest.mark.parametrize(
        "text",
        [
            "leave me alone",
            "Stop messaging me, please",
            "don't text me anymore",
            "do not contact me ever",
            "go away",
            "fuck off",
            "block you",
            "unsubscribe",
            "stop all contact",
            "remove me from your list",
            "оставь меня в покое",
            "не пиши мне больше",
            "не пишите мне",
            "отстань",
            "хватит писать",
            "больше не пиши",
        ],
    )
    def test_drops_silently_with_suppression(self, text: str) -> None:
        v = evaluate_incoming(text)
        assert not v.allowed, text
        assert v.action is SafetyAction.DROP_SILENTLY
        assert "stop_request" in v.effective_flags
        assert v.suppression_hours == 72.0
        assert v.effective_sales_allowed is False
        assert v.effective_proactive_allowed is False
        assert v.handoff_required is False
        # No reply by default — orchestrator drops silently.
        assert v.safe_reply is None

    def test_does_not_match_benign_stop(self) -> None:
        # Common false-positives we want to allow.
        for ok in [
            "stop being so cute",
            "i can't stop thinking about you",
            "stop the music",
            "leave a tip for the bartender",
        ]:
            v = evaluate_incoming(ok)
            assert v.allowed, ok


# ---------- Pure regex: harassment ----------


class TestHarassmentPatterns:
    @pytest.mark.parametrize(
        "text",
        [
            "i will kill you",
            "i'm gonna find you",
            "i hope you die in a fire",
            "you're a whore",
            "you are a slut",
        ],
    )
    def test_handoff(self, text: str) -> None:
        v = evaluate_incoming(text)
        assert not v.allowed
        assert v.action is SafetyAction.HANDOFF_TO_HUMAN
        assert "harassment" in v.effective_flags
        assert v.handoff_required is True
        assert v.suppression_hours == 24.0


# ---------- Pure regex: chargeback ----------


class TestChargebackPatterns:
    @pytest.mark.parametrize(
        "text",
        [
            "i want a refund",
            "i'm gonna refund this",
            "I'll dispute the charge",
            "chargeback incoming",
            "i'm reporting you to telegram support",
        ],
    )
    def test_handoff(self, text: str) -> None:
        v = evaluate_incoming(text)
        assert not v.allowed, text
        assert v.action is SafetyAction.HANDOFF_TO_HUMAN
        assert "chargeback" in v.effective_flags
        assert v.handoff_required is True


# ---------- Pure regex: intoxication ----------


class TestIntoxicationPatterns:
    @pytest.mark.parametrize(
        "text",
        [
            "i'm so drunk rn",
            "i am wasted lol",
            "i'm high af",
            "i'm hammered",
            "blacked out last night",
        ],
    )
    def test_allows_but_blocks_sales(self, text: str) -> None:
        v = evaluate_incoming(text)
        assert v.allowed, text
        assert "intoxication" in v.effective_flags
        assert v.effective_sales_allowed is False
        assert v.effective_proactive_allowed is False


# ---------- Effective fields default behaviour ----------


def test_allow_verdict_defaults_to_open() -> None:
    v = evaluate_incoming("hi how are you")
    assert v.allowed
    assert v.effective_risk_level is RiskLevel.NONE
    assert v.effective_sales_allowed is True
    assert v.effective_proactive_allowed is True


def test_minor_verdict_blocks_everything() -> None:
    v = evaluate_incoming("i'm 15 btw")
    assert v.action is SafetyAction.HANDOFF_TO_HUMAN
    assert v.effective_risk_level is RiskLevel.CRITICAL
    assert v.effective_sales_allowed is False
    assert v.effective_proactive_allowed is False


def test_evaluate_reply_still_works_for_legacy_callers() -> None:
    v = evaluate_reply("yes I'm an AI assistant")
    assert not v.allowed
    assert v.severity is SafetySeverity.HIGH
    assert "output_ai_self_disclosure" in v.reasons


# ---------- SafetyEngine.precheck persistence ----------


async def _client(session, fan_id: int):
    return await get_or_create_client(
        session, fan_id=fan_id, username="u", first_name="U", last_name=None
    )


async def _events(session, fan_id: int) -> list[EventLog]:
    rows = (
        (
            await session.execute(
                select(EventLog).where(EventLog.fan_id == fan_id).order_by(EventLog.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def test_precheck_allow_writes_no_event(session) -> None:
    client = await _client(session, fan_id=1)
    out = await SafetyEngine.precheck(session, client=client, text="hey love")
    assert out.verdict.action is SafetyAction.ALLOW
    assert out.flags_added == ()
    assert out.suppression_applied is False
    assert out.handoff_applied is False
    assert await _events(session, fan_id=1) == []


async def test_precheck_minor_persists_handoff_and_risk(session) -> None:
    client = await _client(session, fan_id=2)
    out = await SafetyEngine.precheck(session, client=client, text="i'm 15 btw")
    assert out.verdict.action is SafetyAction.HANDOFF_TO_HUMAN
    assert out.handoff_applied is True
    assert out.persisted_risk_level is RiskLevel.CRITICAL
    assert "minors" in out.flags_added
    rows = await _events(session, fan_id=2)
    types = [r.event_type for r in rows]
    assert "safety_flagged" in types
    assert "handoff_required" in types
    # Persisted state on client.
    await session.refresh(client)
    assert client.handoff_required is True
    assert client.risk_level == "critical"
    assert "minors" in (client.flags or "")


async def test_precheck_stop_request_sets_72h_suppression(session) -> None:
    client = await _client(session, fan_id=3)
    out = await SafetyEngine.precheck(session, client=client, text="leave me alone please")
    assert out.verdict.action is SafetyAction.DROP_SILENTLY
    assert out.suppression_applied is True
    assert out.handoff_applied is False
    await session.refresh(client)
    assert client.suppression_until is not None
    assert "stop_request" in (client.flags or "")
    rows = await _events(session, fan_id=3)
    suppression_rows = [r for r in rows if r.event_type == "suppression_applied"]
    assert len(suppression_rows) == 1
    payload = json.loads(suppression_rows[0].payload)
    # The reason payload includes the flags csv.
    assert "stop_request" in payload["reason"]


async def test_precheck_chargeback_handoff_no_suppression(session) -> None:
    client = await _client(session, fan_id=4)
    out = await SafetyEngine.precheck(
        session, client=client, text="i want a refund and i'll dispute the charge"
    )
    assert out.verdict.action is SafetyAction.HANDOFF_TO_HUMAN
    assert out.handoff_applied is True
    assert out.suppression_applied is False


async def test_precheck_intoxication_no_handoff_but_flag_persisted(session) -> None:
    client = await _client(session, fan_id=5)
    out = await SafetyEngine.precheck(session, client=client, text="i'm so drunk lol")
    assert out.verdict.action is SafetyAction.ALLOW
    assert out.handoff_applied is False
    assert "intoxication" in out.flags_added
    await session.refresh(client)
    assert "intoxication" in (client.flags or "")
    # Risk should be at least LOW.
    assert client.risk_level in {"low", "medium", "high", "critical"}


async def test_precheck_already_flagged_escalates_nonconsent(session) -> None:
    client = await _client(session, fan_id=6)
    # Pre-existing risky flag on the client.
    await update_safety_flags(session, fan_id=6, add=["non_consent"])
    await session.refresh(client)
    out = await SafetyEngine.precheck(session, client=client, text="non-consent fantasy please")
    # When the fan is already flagged, the engine forces handoff.
    assert out.verdict.handoff_required is True


async def test_precheck_does_not_re_escalate_risk_downward(session) -> None:
    """An LOW-risk turn after a CRITICAL one must not lower the persisted level."""
    client = await _client(session, fan_id=7)
    # First turn: minor → CRITICAL.
    await SafetyEngine.precheck(session, client=client, text="i'm 15")
    await session.refresh(client)
    assert client.risk_level == "critical"
    # Second turn: clean text → ALLOW. Risk must stay CRITICAL.
    out = await SafetyEngine.precheck(session, client=client, text="hi how are you")
    await session.refresh(client)
    assert out.verdict.action is SafetyAction.ALLOW
    assert client.risk_level == "critical"


async def test_precheck_idempotent_same_flag_not_re_emitted(session) -> None:
    client = await _client(session, fan_id=8)
    await SafetyEngine.precheck(session, client=client, text="leave me alone")
    # New SafetyEngine call with same text on same client: flag already
    # present, so flags_added should be empty on the second call.
    await session.refresh(client)
    out2 = await SafetyEngine.precheck(session, client=client, text="leave me alone")
    assert out2.flags_added == ()


# ---------- Postcheck ----------


async def test_postcheck_writes_event_on_block(session) -> None:
    client = await _client(session, fan_id=9)
    v = await SafetyEngine.postcheck(session, client=client, text="my number is +1 415 555 0199")
    assert not v.allowed
    rows = await _events(session, fan_id=9)
    assert any(r.event_type == "safety_flagged" for r in rows)


async def test_postcheck_allow_writes_nothing(session) -> None:
    client = await _client(session, fan_id=10)
    v = await SafetyEngine.postcheck(session, client=client, text="hey love 💛")
    assert v.allowed
    assert await _events(session, fan_id=10) == []

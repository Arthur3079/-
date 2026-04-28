"""Layer 1 tests: lifecycle/journey CRM methods + observability events.

Covers every new method in `sonya.crm.repository` plus the flag helpers
in `sonya.crm.flags`. Also asserts that state-changing repo calls write
matching rows into `events_log`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.crm.facts import upsert_fact
from sonya.crm.flags import add_flag, has_flag, parse_flags, remove_flag, serialize_flags
from sonya.crm.repository import (
    clear_handoff,
    get_client_profile,
    get_or_create_client,
    is_suppressed,
    list_recent_facts,
    list_recent_messages,
    mark_inbound_seen,
    mark_offer_sent,
    mark_outbound_sent,
    mark_purchase_recorded,
    save_message,
    set_handoff_required,
    set_suppression,
    set_suppression_for,
    update_fan_type,
    update_risk_level,
    update_safety_flags,
    update_stage,
)
from sonya.db import models  # noqa: F401  registers tables on metadata
from sonya.db.base import Base
from sonya.db.models import EventLog, MessageDirection
from sonya.journey import RiskLevel, Stage
from sonya.observability import EventType, write_event


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _client(session, fan_id: int = 1):
    return await get_or_create_client(
        session, fan_id=fan_id, username="u", first_name="U", last_name=None
    )


async def _events(session, fan_id: int | None = None) -> list[EventLog]:
    stmt = select(EventLog).order_by(EventLog.id.asc())
    if fan_id is not None:
        stmt = stmt.where(EventLog.fan_id == fan_id)
    return list((await session.execute(stmt)).scalars().all())


# ---------- Flag helpers (pure) ---------------------------------------------


def test_parse_flags_handles_empty_and_whitespace() -> None:
    assert parse_flags(None) == []
    assert parse_flags("") == []
    assert parse_flags(" , ,") == []
    assert parse_flags(" a , b,c ") == ["a", "b", "c"]


def test_parse_flags_dedupes_preserves_order() -> None:
    assert parse_flags("a,b,a,c,b") == ["a", "b", "c"]


def test_serialize_roundtrip() -> None:
    assert serialize_flags([]) is None
    assert serialize_flags(["a", "b"]) == "a,b"
    assert serialize_flags(["a", "a", "b", " ", ""]) == "a,b"


def test_add_remove_has_flag() -> None:
    raw = None
    raw = add_flag(raw, "vulnerable")
    raw = add_flag(raw, "off_platform")
    assert has_flag(raw, "vulnerable")
    assert has_flag(raw, "off_platform")
    assert not has_flag(raw, "stop_request")
    assert add_flag(raw, "vulnerable") == raw  # idempotent
    raw = remove_flag(raw, "vulnerable")
    assert not has_flag(raw, "vulnerable")
    assert has_flag(raw, "off_platform")
    raw = remove_flag(raw, "missing")  # no-op
    assert raw == "off_platform"


# ---------- Default lifecycle values on create ------------------------------


async def test_new_client_has_welcome_stage_and_no_risk(session) -> None:
    client = await _client(session, fan_id=10)
    assert client.current_stage == Stage.WELCOME.value
    assert client.risk_level == RiskLevel.NONE.value
    assert client.consecutive_outbound_without_reply == 0
    assert client.handoff_required is False
    assert client.suppression_until is None
    assert client.last_inbound_at is None
    assert client.last_outbound_at is None
    assert client.last_offer_at is None
    assert client.last_purchase_at is None


# ---------- update_stage ----------------------------------------------------


async def test_update_stage_records_event_and_skips_no_op(session) -> None:
    await _client(session, fan_id=11)
    changed = await update_stage(session, fan_id=11, stage=Stage.QUALIFY, reason="2 replies")
    assert changed is True
    second = await update_stage(session, fan_id=11, stage="qualify")
    assert second is False  # no-op
    events = [e for e in await _events(session, fan_id=11) if e.event_type == "stage_changed"]
    assert len(events) == 1
    payload = json.loads(events[0].payload)
    assert payload["from"] == "welcome"
    assert payload["to"] == "qualify"
    assert payload["reason"] == "2 replies"


async def test_update_stage_rejects_unknown_value(session) -> None:
    await _client(session, fan_id=12)
    with pytest.raises(ValueError):
        await update_stage(session, fan_id=12, stage="not_a_stage")


# ---------- update_risk_level -----------------------------------------------


async def test_update_risk_level_writes_event(session) -> None:
    await _client(session, fan_id=13)
    changed = await update_risk_level(
        session, fan_id=13, risk_level=RiskLevel.HIGH, reason="vulnerable signal"
    )
    assert changed is True
    again = await update_risk_level(session, fan_id=13, risk_level="high")
    assert again is False
    rows = await _events(session, fan_id=13)
    types = [r.event_type for r in rows]
    assert types.count("risk_level_changed") == 1


# ---------- update_fan_type -------------------------------------------------


async def test_update_fan_type_writes_event_only_when_changed(session) -> None:
    await _client(session, fan_id=14)
    assert await update_fan_type(session, fan_id=14, fan_type="WHALE", confidence="high") is True
    assert await update_fan_type(session, fan_id=14, fan_type="WHALE", confidence="high") is False
    rows = await _events(session, fan_id=14)
    assert sum(1 for r in rows if r.event_type == "fan_type_updated") == 1


# ---------- update_safety_flags ---------------------------------------------


async def test_safety_flags_add_remove_and_event_payload(session) -> None:
    await _client(session, fan_id=15)
    flags = await update_safety_flags(session, fan_id=15, add=["vulnerable", "off_platform"])
    assert set(flags) == {"vulnerable", "off_platform"}
    flags = await update_safety_flags(
        session, fan_id=15, add=["vulnerable"], remove=["off_platform"]
    )
    assert flags == ["vulnerable"]
    # No-op should NOT write a second flags_updated event.
    flags = await update_safety_flags(session, fan_id=15, add=["vulnerable"])
    rows = [r for r in await _events(session, fan_id=15) if r.event_type == "flags_updated"]
    assert len(rows) == 2
    last_payload = json.loads(rows[-1].payload)
    assert last_payload["added"] == []
    assert last_payload["removed"] == ["off_platform"]


# ---------- suppression -----------------------------------------------------


async def test_set_suppression_for_writes_event_and_is_suppressed_true(session) -> None:
    await _client(session, fan_id=16)
    until = await set_suppression_for(session, fan_id=16, hours=72, reason="stop_request")
    assert until > datetime.now(UTC)
    assert await is_suppressed(session, fan_id=16) is True
    rows = [r for r in await _events(session, fan_id=16) if r.event_type == "suppression_applied"]
    assert len(rows) == 1


async def test_clear_suppression_writes_event(session) -> None:
    await _client(session, fan_id=17)
    await set_suppression_for(session, fan_id=17, hours=1, reason="r")
    await set_suppression(session, fan_id=17, until=None, reason="lifted")
    rows = [r for r in await _events(session, fan_id=17) if r.event_type == "suppression_cleared"]
    assert len(rows) == 1
    assert await is_suppressed(session, fan_id=17) is False


async def test_expired_suppression_is_not_suppressed(session) -> None:
    await _client(session, fan_id=18)
    past = datetime.now(UTC) - timedelta(hours=1)
    await set_suppression(session, fan_id=18, until=past, reason="x")
    assert await is_suppressed(session, fan_id=18) is False


# ---------- handoff ---------------------------------------------------------


async def test_handoff_set_and_clear(session) -> None:
    await _client(session, fan_id=19)
    assert await set_handoff_required(session, fan_id=19, reason="minor") is True
    assert await set_handoff_required(session, fan_id=19, reason="minor") is False
    assert await clear_handoff(session, fan_id=19, reason="resolved") is True
    rows = await _events(session, fan_id=19)
    types = [r.event_type for r in rows]
    assert types.count("handoff_required") == 1
    assert types.count("handoff_cleared") == 1


# ---------- inbound / outbound counters -------------------------------------


async def test_outbound_counter_increments_and_resets(session) -> None:
    client = await _client(session, fan_id=20)
    assert client.consecutive_outbound_without_reply == 0
    n1 = await mark_outbound_sent(session, fan_id=20)
    n2 = await mark_outbound_sent(session, fan_id=20)
    n3 = await mark_outbound_sent(session, fan_id=20)
    assert (n1, n2, n3) == (1, 2, 3)
    await mark_inbound_seen(session, fan_id=20)
    res = await session.execute(
        select(models.Client.consecutive_outbound_without_reply).where(  # noqa
            models.Client.fan_id == 20
        )
    )
    assert res.scalar_one() == 0


def _eq_utc(stored, expected) -> bool:
    """SQLite drops tz on `DateTime(timezone=True)`; treat naive as UTC."""
    if stored is None or expected is None:
        return stored is expected
    s = stored if stored.tzinfo else stored.replace(tzinfo=UTC)
    e = expected if expected.tzinfo else expected.replace(tzinfo=UTC)
    return s == e


async def test_mark_inbound_sets_last_inbound_at(session) -> None:
    await _client(session, fan_id=21)
    when = datetime(2026, 4, 26, 18, 0, tzinfo=UTC)
    await mark_inbound_seen(session, fan_id=21, at=when)
    profile = await get_client_profile(session, fan_id=21)
    assert profile is not None
    assert _eq_utc(profile.client.last_inbound_at, when)
    assert _eq_utc(profile.client.last_active, when)


async def test_mark_outbound_sets_last_outbound_at(session) -> None:
    await _client(session, fan_id=22)
    when = datetime(2026, 4, 26, 19, 0, tzinfo=UTC)
    await mark_outbound_sent(session, fan_id=22, at=when)
    profile = await get_client_profile(session, fan_id=22)
    assert profile is not None
    assert _eq_utc(profile.client.last_outbound_at, when)


async def test_mark_offer_and_purchase(session) -> None:
    await _client(session, fan_id=23)
    await mark_outbound_sent(session, fan_id=23)
    await mark_outbound_sent(session, fan_id=23)
    await mark_offer_sent(session, fan_id=23)
    await mark_purchase_recorded(session, fan_id=23)
    profile = await get_client_profile(session, fan_id=23)
    assert profile is not None
    assert profile.client.last_offer_at is not None
    assert profile.client.last_purchase_at is not None
    # Purchase is a strong inbound; counter resets.
    assert profile.client.consecutive_outbound_without_reply == 0


# ---------- profile bundle / list helpers -----------------------------------


async def test_get_client_profile_returns_none_for_unknown(session) -> None:
    assert await get_client_profile(session, fan_id=999) is None


async def test_list_recent_messages_orders_desc_and_limits(session) -> None:
    await _client(session, fan_id=30)
    base = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    for i in range(5):
        await save_message(
            session,
            fan_id=30,
            tg_message_id=i,
            direction=MessageDirection.INCOMING,
            content=f"m{i}",
            timestamp=base + timedelta(minutes=i),
        )
    msgs = await list_recent_messages(session, fan_id=30, limit=3)
    assert [m.content for m in msgs] == ["m4", "m3", "m2"]


async def test_list_recent_facts_returns_views(session) -> None:
    await _client(session, fan_id=31)
    await upsert_fact(session, fan_id=31, key="city", value="NYC")
    await upsert_fact(session, fan_id=31, key="pet", value="cat")
    facts = await list_recent_facts(session, fan_id=31, limit=10)
    assert {f.key for f in facts} == {"city", "pet"}


async def test_get_client_profile_bundles_facts_and_messages(session) -> None:
    await _client(session, fan_id=32)
    await save_message(
        session,
        fan_id=32,
        tg_message_id=1,
        direction=MessageDirection.INCOMING,
        content="hello",
    )
    await upsert_fact(session, fan_id=32, key="name", value="Alex")
    profile = await get_client_profile(session, fan_id=32)
    assert profile is not None
    assert profile.client.fan_id == 32
    assert len(profile.recent_messages) == 1
    assert profile.facts[0].key == "name"


# ---------- write_event direct ----------------------------------------------


async def test_write_event_serializes_datetime_in_payload(session) -> None:
    await _client(session, fan_id=40)
    when = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    await write_event(
        session,
        fan_id=40,
        event_type=EventType.MESSAGE_SCHEDULED,
        payload={"due": when, "kind": "ghost_recovery"},
    )
    rows = await _events(session, fan_id=40)
    assert rows[-1].event_type == "message_scheduled"
    payload = json.loads(rows[-1].payload)
    assert payload["due"] == "2026-01-01T00:00:00+00:00"
    assert payload["kind"] == "ghost_recovery"


async def test_write_event_accepts_string_event_type(session) -> None:
    await write_event(session, fan_id=None, event_type="custom_type", payload=None)
    rows = await _events(session)
    assert any(r.event_type == "custom_type" for r in rows)

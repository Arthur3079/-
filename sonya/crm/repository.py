"""Async repositories on top of SQLAlchemy.

This module owns lifecycle state mutations on `Client` and the relational
writes around `Message` / `Followup` / `SalesAttempt`. Business policies
(when to change a stage, whether to block a send) live in
`sonya.journey` (Layer 3) — this layer just exposes the verbs.

Every state-changing call writes one matching `events_log` row via
`sonya.observability.write_event` so the runtime stays auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.crm.facts import FactView, list_facts
from sonya.crm.flags import add_flag as _add_flag
from sonya.crm.flags import parse_flags as _parse_flags
from sonya.crm.flags import remove_flag as _remove_flag
from sonya.crm.flags import serialize_flags as _serialize_flags
from sonya.db.models import Client, FanStatus, Message, MessageDirection, MessageMediaType
from sonya.journey import RiskLevel, Stage, is_valid_risk_level, is_valid_stage
from sonya.observability import EventType, write_event

# ---------- Identity / messages ---------------------------------------------


async def get_or_create_client(
    session: AsyncSession,
    *,
    fan_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> Client:
    """Find a client by `fan_id` or create one. Refreshes username/name
    from the latest Telegram profile so renames propagate."""
    now = datetime.now(UTC)
    res = await session.execute(select(Client).where(Client.fan_id == fan_id))
    client = res.scalar_one_or_none()
    if client is None:
        client = Client(
            fan_id=fan_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            display_name=_display_name(first_name, last_name, username),
            status=FanStatus.ACTIVE,
            current_stage=Stage.WELCOME.value,
            risk_level=RiskLevel.NONE.value,
            first_seen=now,
            last_active=now,
        )
        session.add(client)
        await session.flush()
        return client

    client.username = username
    client.first_name = first_name
    client.last_name = last_name
    client.display_name = _display_name(first_name, last_name, username) or client.display_name
    client.last_active = now
    return client


async def save_message(
    session: AsyncSession,
    *,
    fan_id: int,
    tg_message_id: int | None,
    direction: MessageDirection,
    content: str | None,
    media_type: MessageMediaType = MessageMediaType.TEXT,
    timestamp: datetime | None = None,
) -> Message:
    msg = Message(
        fan_id=fan_id,
        tg_message_id=tg_message_id,
        direction=direction,
        media_type=media_type,
        content=content,
        timestamp=timestamp or datetime.now(UTC),
    )
    session.add(msg)
    await session.flush()
    return msg


async def list_recent_messages(
    session: AsyncSession, *, fan_id: int, limit: int = 20
) -> list[Message]:
    """Most recent messages first → oldest last. Returns up to `limit`."""
    if limit <= 0:
        return []
    stmt = (
        select(Message)
        .where(Message.fan_id == fan_id)
        .order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def count_inbound_messages(session: AsyncSession, *, fan_id: int) -> int:
    """Total all-time inbound message count for a fan.

    Used by JourneyEngine to derive the stage (welcome → warmup → qualify)
    and by CadenceEngine to enforce `MIN_INBOUND_BEFORE_OFFER`.
    """
    from sqlalchemy import func

    from sonya.db.models import MessageDirection

    stmt = (
        select(func.count())
        .select_from(Message)
        .where(
            Message.fan_id == fan_id,
            Message.direction == MessageDirection.INCOMING,
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def list_recent_facts(
    session: AsyncSession, *, fan_id: int, limit: int = 50
) -> list[FactView]:
    facts = await list_facts(session, fan_id=fan_id)
    return facts[:limit] if limit > 0 else facts


# ---------- Profile bundle --------------------------------------------------


@dataclass(frozen=True)
class ClientProfile:
    """Read-only bundle of everything the dialogue layer needs about a
    fan in one place."""

    client: Client
    recent_messages: tuple[Message, ...]
    facts: tuple[FactView, ...]


async def get_client_profile(
    session: AsyncSession,
    *,
    fan_id: int,
    history_limit: int = 20,
    fact_limit: int = 50,
) -> ClientProfile | None:
    """Load client + recent messages + recent facts in three queries."""
    res = await session.execute(select(Client).where(Client.fan_id == fan_id))
    client = res.scalar_one_or_none()
    if client is None:
        return None
    msgs = await list_recent_messages(session, fan_id=fan_id, limit=history_limit)
    facts = await list_recent_facts(session, fan_id=fan_id, limit=fact_limit)
    return ClientProfile(
        client=client,
        recent_messages=tuple(msgs),
        facts=tuple(facts),
    )


# ---------- Lifecycle / journey state ---------------------------------------


async def update_stage(
    session: AsyncSession,
    *,
    fan_id: int,
    stage: Stage | str,
    reason: str | None = None,
) -> bool:
    """Set `clients.current_stage`. No-op if value already matches.

    Returns True iff the stage actually changed."""
    value = stage.value if isinstance(stage, Stage) else stage
    if not is_valid_stage(value):
        raise ValueError(f"unknown stage {value!r}")
    client = await _require_client(session, fan_id)
    if client.current_stage == value:
        return False
    previous = client.current_stage
    client.current_stage = value
    await write_event(
        session,
        fan_id=fan_id,
        event_type=EventType.STAGE_CHANGED,
        payload={"from": previous, "to": value, "reason": reason},
    )
    return True


async def update_risk_level(
    session: AsyncSession,
    *,
    fan_id: int,
    risk_level: RiskLevel | str,
    reason: str | None = None,
) -> bool:
    value = risk_level.value if isinstance(risk_level, RiskLevel) else risk_level
    if not is_valid_risk_level(value):
        raise ValueError(f"unknown risk_level {value!r}")
    client = await _require_client(session, fan_id)
    if client.risk_level == value:
        return False
    previous = client.risk_level
    client.risk_level = value
    await write_event(
        session,
        fan_id=fan_id,
        event_type=EventType.RISK_LEVEL_CHANGED,
        payload={"from": previous, "to": value, "reason": reason},
    )
    return True


async def update_fan_type(
    session: AsyncSession,
    *,
    fan_id: int,
    fan_type: str | None,
    confidence: str | None = None,
) -> bool:
    client = await _require_client(session, fan_id)
    changed = False
    if fan_type is not None and client.fan_type != fan_type:
        client.fan_type = fan_type
        changed = True
    if confidence is not None and client.type_confidence != confidence:
        client.type_confidence = confidence
        changed = True
    if changed:
        await write_event(
            session,
            fan_id=fan_id,
            event_type=EventType.FAN_TYPE_UPDATED,
            payload={"fan_type": client.fan_type, "confidence": client.type_confidence},
        )
    return changed


async def update_safety_flags(
    session: AsyncSession,
    *,
    fan_id: int,
    add: list[str] | None = None,
    remove: list[str] | None = None,
) -> list[str]:
    """Apply incremental flag changes. Returns the resulting flag list."""
    client = await _require_client(session, fan_id)
    raw = client.flags
    before = _parse_flags(raw)
    for f in add or []:
        raw = _add_flag(raw, f)
    for f in remove or []:
        raw = _remove_flag(raw, f)
    after = _parse_flags(raw)
    if after != before:
        client.flags = raw
        await write_event(
            session,
            fan_id=fan_id,
            event_type=EventType.FLAGS_UPDATED,
            payload={
                "added": sorted(set(after) - set(before)),
                "removed": sorted(set(before) - set(after)),
                "current": after,
            },
        )
    return after


async def set_suppression(
    session: AsyncSession,
    *,
    fan_id: int,
    until: datetime | None,
    reason: str | None = None,
) -> None:
    """Set `suppression_until`. Pass `until=None` to clear."""
    client = await _require_client(session, fan_id)
    previous = client.suppression_until
    client.suppression_until = until
    if until is None:
        if previous is not None:
            await write_event(
                session,
                fan_id=fan_id,
                event_type=EventType.SUPPRESSION_CLEARED,
                payload={"reason": reason},
            )
        return
    await write_event(
        session,
        fan_id=fan_id,
        event_type=EventType.SUPPRESSION_APPLIED,
        payload={
            "until": until,
            "reason": reason,
            "duration_seconds": int((until - datetime.now(UTC)).total_seconds()),
        },
    )


async def set_suppression_for(
    session: AsyncSession,
    *,
    fan_id: int,
    hours: float,
    reason: str | None = None,
    now: datetime | None = None,
) -> datetime:
    """Convenience: set `suppression_until = now + hours` and return that
    timestamp."""
    base = now or datetime.now(UTC)
    until = base + timedelta(hours=hours)
    await set_suppression(session, fan_id=fan_id, until=until, reason=reason)
    return until


async def is_suppressed(session: AsyncSession, *, fan_id: int, now: datetime | None = None) -> bool:
    """True iff `suppression_until` is set and in the future.

    Tolerant of naive datetimes returned by SQLite (column declares
    `timezone=True` but SQLite stores text without tz). Naive values are
    interpreted as UTC.
    """
    client = await _require_client(session, fan_id)
    until = _to_utc(client.suppression_until)
    if until is None:
        return False
    return until > (now or datetime.now(UTC))


def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def set_handoff_required(
    session: AsyncSession,
    *,
    fan_id: int,
    reason: str | None = None,
) -> bool:
    client = await _require_client(session, fan_id)
    if client.handoff_required:
        return False
    client.handoff_required = True
    await write_event(
        session,
        fan_id=fan_id,
        event_type=EventType.HANDOFF_REQUIRED,
        payload={"reason": reason},
    )
    return True


async def clear_handoff(
    session: AsyncSession,
    *,
    fan_id: int,
    reason: str | None = None,
) -> bool:
    client = await _require_client(session, fan_id)
    if not client.handoff_required:
        return False
    client.handoff_required = False
    await write_event(
        session,
        fan_id=fan_id,
        event_type=EventType.HANDOFF_CLEARED,
        payload={"reason": reason},
    )
    return True


# ---------- Inbound / outbound counters -------------------------------------


async def mark_inbound_seen(
    session: AsyncSession,
    *,
    fan_id: int,
    at: datetime | None = None,
) -> None:
    """Bookkeeping after a fan→Sonya message has been persisted.

    Resets `consecutive_outbound_without_reply` to 0 and updates
    `last_inbound_at` / `last_active`.
    """
    when = at or datetime.now(UTC)
    client = await _require_client(session, fan_id)
    client.last_inbound_at = when
    client.last_active = when
    client.consecutive_outbound_without_reply = 0


async def mark_outbound_sent(
    session: AsyncSession,
    *,
    fan_id: int,
    at: datetime | None = None,
) -> int:
    """Bookkeeping after a Sonya→fan message has been persisted.

    Increments `consecutive_outbound_without_reply` and updates
    `last_outbound_at` / `last_active`. Returns the new counter value.
    """
    when = at or datetime.now(UTC)
    client = await _require_client(session, fan_id)
    client.last_outbound_at = when
    client.last_active = when
    client.consecutive_outbound_without_reply = client.consecutive_outbound_without_reply + 1
    return client.consecutive_outbound_without_reply


async def mark_offer_sent(
    session: AsyncSession,
    *,
    fan_id: int,
    at: datetime | None = None,
) -> None:
    when = at or datetime.now(UTC)
    client = await _require_client(session, fan_id)
    client.last_offer_at = when


async def mark_purchase_recorded(
    session: AsyncSession,
    *,
    fan_id: int,
    at: datetime | None = None,
) -> None:
    """Called from payment_bot when a successful payment is processed.

    Sets `last_purchase_at` and resets `consecutive_outbound_without_reply`
    (a purchase is a strong inbound signal).
    """
    when = at or datetime.now(UTC)
    client = await _require_client(session, fan_id)
    client.last_purchase_at = when
    client.last_active = when
    client.consecutive_outbound_without_reply = 0


# ---------- Helpers ---------------------------------------------------------


async def _require_client(session: AsyncSession, fan_id: int) -> Client:
    res = await session.execute(select(Client).where(Client.fan_id == fan_id))
    client = res.scalar_one_or_none()
    if client is None:
        raise LookupError(f"client fan_id={fan_id} not found")
    return client


def _display_name(first: str | None, last: str | None, username: str | None) -> str | None:
    parts = [p for p in (first, last) if p]
    if parts:
        return " ".join(parts)
    return f"@{username}" if username else None


# Re-export flag helpers so callers can `from sonya.crm.repository import ...`
# without importing both modules.
__all__ = [
    "ClientProfile",
    "clear_handoff",
    "get_client_profile",
    "get_or_create_client",
    "is_suppressed",
    "list_recent_facts",
    "list_recent_messages",
    "mark_inbound_seen",
    "mark_offer_sent",
    "mark_outbound_sent",
    "mark_purchase_recorded",
    "save_message",
    "set_handoff_required",
    "set_suppression",
    "set_suppression_for",
    "update_fan_type",
    "update_risk_level",
    "update_safety_flags",
    "update_stage",
    "_serialize_flags",
]

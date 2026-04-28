"""Facts repository — what we know about a fan.

The schema for `Fact` (key/value/confidence/source_message_id/date_disclosed)
already exists in `sonya/db/models.py`. This module is the thin async API on
top of it: idempotent `upsert_fact`, list/dict accessors, delete.

Fact extraction (parsing free-form messages into facts) is intentionally NOT
in this patch — it requires either rule-based heuristics tuned per language
or a small LLM call, both of which deserve their own design. For now,
operators / future admin tooling will call `upsert_fact` directly and the
LLM context will use whatever facts exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import Fact

VALID_CONFIDENCES = ("low", "mid", "high")


@dataclass(frozen=True)
class FactView:
    """Read-only snapshot of a fact, decoupled from ORM lifecycle."""

    key: str
    value: str
    confidence: str
    date_disclosed: datetime
    source_message_id: int | None


async def upsert_fact(
    session: AsyncSession,
    *,
    fan_id: int,
    key: str,
    value: str,
    confidence: str = "mid",
    source_message_id: int | None = None,
    date_disclosed: datetime | None = None,
) -> Fact:
    """Create or update a fact for `(fan_id, key)`. UNIQUE constraint enforced
    by the schema (`uq_facts_fan_key`).

    Idempotent on identical (value, confidence) — only touches the row if
    something changed.
    """
    if not key or not value:
        raise ValueError("upsert_fact requires non-empty key and value")
    if confidence not in VALID_CONFIDENCES:
        raise ValueError(f"confidence must be one of {VALID_CONFIDENCES}, got {confidence!r}")
    when = date_disclosed or datetime.now(UTC)

    stmt = select(Fact).where(Fact.fan_id == fan_id, Fact.key == key)
    existing = (await session.execute(stmt)).scalar_one_or_none()

    if existing is None:
        fact = Fact(
            fan_id=fan_id,
            key=key,
            value=value,
            confidence=confidence,
            source_message_id=source_message_id,
            date_disclosed=when,
        )
        session.add(fact)
        await session.flush()
        return fact

    changed = False
    if existing.value != value:
        existing.value = value
        changed = True
    if existing.confidence != confidence:
        existing.confidence = confidence
        changed = True
    if source_message_id is not None and existing.source_message_id != source_message_id:
        existing.source_message_id = source_message_id
        changed = True
    if changed:
        existing.date_disclosed = when
        await session.flush()
    return existing


async def list_facts(session: AsyncSession, *, fan_id: int) -> list[FactView]:
    """All known facts for a fan, ordered by most recent first."""
    stmt = (
        select(Fact)
        .where(Fact.fan_id == fan_id)
        .order_by(Fact.date_disclosed.desc(), Fact.id.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        FactView(
            key=r.key,
            value=r.value,
            confidence=r.confidence,
            date_disclosed=r.date_disclosed,
            source_message_id=r.source_message_id,
        )
        for r in rows
    ]


async def facts_dict(session: AsyncSession, *, fan_id: int) -> dict[str, str]:
    """Map of `{key: value}` for the LLM context. Latest disclosure wins per key.

    Useful for `render_client_card`: we only want one entry per key.
    """
    facts = await list_facts(session, fan_id=fan_id)
    out: dict[str, str] = {}
    for f in facts:
        # list_facts is most-recent-first; first occurrence per key wins.
        out.setdefault(f.key, f.value)
    return out


async def delete_fact(
    session: AsyncSession,
    *,
    fan_id: int,
    key: str,
) -> bool:
    """Remove a fact. Returns True if a row was deleted."""
    stmt = select(Fact).where(Fact.fan_id == fan_id, Fact.key == key)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is None:
        return False
    await session.delete(existing)
    await session.flush()
    return True

"""Lightweight fan-type classifier (Phase-4 MVP).

Real Sonya has 30 fan types (A1..G3) defined in
`knowledge/ai_training/02_fan_types.md`. That requires real signals
(communication style, kinks, attachment, tipping pattern) and ideally an LLM
classifier. We're not there yet.

This module returns a *coarse* category from a handful of cheap signals — all
read from the existing `clients` row + an incoming-message count — so the
dialogue orchestrator can at least steer retrieval ("send the welcome flow
playbook for newcomers", "use ghost-recovery copy for someone returning after
silence").

The classifier is **read-only**. We don't write `client.fan_type` here, to
avoid clobbering manual A1..G3 labels an operator may set later. Persistence
is a separate concern for a future patch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import Client, Message, MessageDirection


class FanTypeLite(str, Enum):
    """Coarse buckets used for retrieval/playbook steering."""

    NEWCOMER = "newcomer"
    REGULAR = "regular"
    WHALE = "whale"
    GHOST = "ghost"
    RISKY = "risky"


@dataclass(frozen=True)
class FanTypeResult:
    fan_type: FanTypeLite
    reasons: tuple[str, ...]


# ---- thresholds (kept inline; tweak via PR, not config — these are policy) ----

NEWCOMER_MAX_INCOMING = 4  # ≤ this many incoming → still a newcomer
WHALE_LIFETIME_SPEND = 100.0  # in stars; tune later
GHOST_DAYS = 7  # last_active older than this → ghost
RISKY_FLAGS = frozenset(
    {
        "vulnerable_lite",
        "vulnerable_strong",
        "off_platform",
        "minor_suspect",
        "non_consent",
        "crisis",
    }
)


def _parse_flags(raw: str | None) -> frozenset[str]:
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


async def classify_fan(
    session: AsyncSession,
    *,
    client: Client,
    now: datetime | None = None,
) -> FanTypeResult:
    """Compute a coarse fan-type label for `client`.

    Order matters: RISKY > GHOST > WHALE > NEWCOMER > REGULAR. The first
    matching rule wins.
    """
    now = now or datetime.now(UTC)
    reasons: list[str] = []

    flags = _parse_flags(client.flags)
    risky_hits = flags & RISKY_FLAGS
    if risky_hits:
        return FanTypeResult(
            fan_type=FanTypeLite.RISKY,
            reasons=tuple(f"flag:{f}" for f in sorted(risky_hits)),
        )

    if client.last_active is not None:
        # SQLite stores naive datetimes; align tz before subtracting.
        last = client.last_active
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if now - last > timedelta(days=GHOST_DAYS):
            return FanTypeResult(
                fan_type=FanTypeLite.GHOST,
                reasons=(f"last_active>{GHOST_DAYS}d",),
            )

    if client.total_spend_lifetime >= WHALE_LIFETIME_SPEND:
        return FanTypeResult(
            fan_type=FanTypeLite.WHALE,
            reasons=(f"lifetime_spend>={WHALE_LIFETIME_SPEND}",),
        )

    incoming_count = await _count_incoming(session, fan_id=client.fan_id)
    if incoming_count <= NEWCOMER_MAX_INCOMING:
        reasons.append(f"incoming_count={incoming_count}")
        return FanTypeResult(fan_type=FanTypeLite.NEWCOMER, reasons=tuple(reasons))

    return FanTypeResult(fan_type=FanTypeLite.REGULAR, reasons=("default",))


async def _count_incoming(session: AsyncSession, *, fan_id: int) -> int:
    stmt = select(func.count(Message.id)).where(
        Message.fan_id == fan_id,
        Message.direction == MessageDirection.INCOMING,
    )
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)

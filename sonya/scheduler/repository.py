"""DB-side primitives for the followup queue."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import Followup


async def enqueue_followup(
    session: AsyncSession,
    *,
    fan_id: int,
    type_: str,
    scheduled_at: datetime,
    note: str | None = None,
    idempotent: bool = True,
) -> Followup:
    """Insert a new pending followup. Caller commits.

    With `idempotent=True` (default), if there is already a pending,
    not-cancelled, not-executed followup of the same `type_` for the same
    `fan_id`, the existing row is returned and `scheduled_at` is updated
    to the *earlier* of the two times. This prevents duplicate aftercare
    queues if the payment webhook fires twice, or duplicate ghost
    recoveries if the scheduler tick races with itself.
    """
    if idempotent:
        existing = await session.execute(
            select(Followup).where(
                Followup.fan_id == fan_id,
                Followup.type == type_,
                Followup.cancelled.is_(False),
                Followup.executed_at.is_(None),
            )
        )
        row = existing.scalars().first()
        if row is not None:
            existing_at = row.scheduled_at
            if existing_at is not None and existing_at.tzinfo is None:
                existing_at = existing_at.replace(tzinfo=UTC)
            if existing_at is None or scheduled_at < existing_at:
                row.scheduled_at = scheduled_at
            await session.flush()
            return row

    row = Followup(
        fan_id=fan_id,
        type=type_,
        scheduled_at=scheduled_at,
        note=note,
        cancelled=False,
    )
    session.add(row)
    await session.flush()
    return row


async def due_followups(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 50,
) -> list[Followup]:
    """Pending, not-cancelled, not-executed followups whose `scheduled_at` ≤ now."""
    now = now or datetime.now(UTC)
    res = await session.execute(
        select(Followup)
        .where(
            Followup.cancelled.is_(False),
            Followup.executed_at.is_(None),
            Followup.scheduled_at <= now,
        )
        .order_by(Followup.scheduled_at.asc())
        .limit(limit)
    )
    return list(res.scalars().all())


async def list_pending(session: AsyncSession, *, fan_id: int | None = None) -> list[Followup]:
    stmt = select(Followup).where(Followup.cancelled.is_(False), Followup.executed_at.is_(None))
    if fan_id is not None:
        stmt = stmt.where(Followup.fan_id == fan_id)
    res = await session.execute(stmt.order_by(Followup.scheduled_at.asc()))
    return list(res.scalars().all())


async def mark_executed(session: AsyncSession, *, followup_id: int) -> None:
    await session.execute(
        sa_update(Followup).where(Followup.id == followup_id).values(executed_at=datetime.now(UTC))
    )


async def cancel_pending_for_fan(
    session: AsyncSession,
    *,
    fan_id: int,
    reason: str | None = None,
) -> int:
    """Cancel every still-pending followup for one fan. Returns number cancelled.

    Implemented as a Python-side update so the `note` concatenation is portable
    across SQLite and Postgres (they disagree on string concat operators).
    """
    pending = await list_pending(session, fan_id=fan_id)
    if not pending:
        return 0
    for row in pending:
        row.cancelled = True
        if reason:
            tail = f"cancelled:{reason}"
            row.note = f"{row.note}\n{tail}" if row.note else tail
    await session.flush()
    return len(pending)

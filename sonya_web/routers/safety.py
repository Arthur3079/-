"""Лента safety-событий и общая статистика."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import EventLog
from sonya_web.deps import get_session

router = APIRouter()

# Безопасные события — те, что относятся к safety/handoff/блокам.
SAFETY_EVENT_TYPES = (
    "safety_flagged",
    "safety_reply_blocked",
    "suppression_applied",
    "handoff_required",
    "regen_attempt_failed",
    "regen_attempt_succeeded",
)


@router.get("/safety/events")
async def safety_events(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, object]:
    rows = (
        (
            await session.execute(
                select(EventLog)
                .where(EventLog.event_type.in_(SAFETY_EVENT_TYPES))
                .order_by(desc(EventLog.timestamp))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    items = [
        {
            "id": e.id,
            "fan_id": e.fan_id,
            "event_type": e.event_type,
            "payload": e.payload,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in rows
    ]
    return {"items": items}


@router.get("/safety/summary")
async def safety_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    window_days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> dict[str, object]:
    window_start = datetime.now(UTC) - timedelta(days=window_days)
    rows = (
        await session.execute(
            select(EventLog.event_type, func.count(EventLog.id))
            .where(
                EventLog.event_type.in_(SAFETY_EVENT_TYPES),
                EventLog.timestamp >= window_start,
            )
            .group_by(EventLog.event_type)
        )
    ).all()
    by_type = {str(t): int(c) for t, c in rows}
    return {
        "window_days": window_days,
        "by_type": by_type,
        "total": sum(by_type.values()),
    }

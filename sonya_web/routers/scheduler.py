"""Очередь proactive-followups."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import Client, Followup
from sonya_web.deps import get_session

router = APIRouter()


@router.get("/scheduler/upcoming")
async def upcoming_followups(
    session: Annotated[AsyncSession, Depends(get_session)],
    horizon_hours: Annotated[int, Query(ge=1, le=720)] = 72,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, object]:
    cutoff = datetime.now(UTC) + timedelta(hours=horizon_hours)
    stmt = (
        select(Followup, Client)
        .join(Client, Client.fan_id == Followup.fan_id)
        .where(
            Followup.cancelled.is_(False),
            Followup.executed_at.is_(None),
            Followup.scheduled_at <= cutoff,
        )
        .order_by(Followup.scheduled_at.asc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    items = [
        {
            "id": f.id,
            "fan_id": f.fan_id,
            "display_name": c.display_name or c.first_name or c.username,
            "type": f.type,
            "scheduled_at": f.scheduled_at.isoformat(),
            "note": f.note,
        }
        for f, c in rows
    ]
    return {"items": items, "horizon_hours": horizon_hours}

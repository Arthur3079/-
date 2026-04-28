"""Воронка по journey-стадиям."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import Client
from sonya.journey.stages import Stage
from sonya_web.deps import get_session

router = APIRouter()

# Порядок стадий в воронке (в порядке прогресса).
FUNNEL_ORDER: list[str] = [
    Stage.WELCOME.value,
    Stage.WARMUP.value,
    Stage.QUALIFY.value,
    Stage.OFFER_PENDING.value,
    Stage.AFTERCARE.value,
    Stage.REPEAT_READY.value,
    Stage.GHOST.value,
    Stage.PAUSED_SAFETY.value,
    Stage.HANDOFF.value,
]


@router.get("/funnel")
async def get_funnel(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    rows = (
        await session.execute(
            select(Client.current_stage, func.count(Client.fan_id)).group_by(Client.current_stage)
        )
    ).all()
    counts = {str(stage or "unknown"): int(count) for stage, count in rows}
    stages = [{"stage": s, "count": counts.get(s, 0)} for s in FUNNEL_ORDER]
    other = sum(v for k, v in counts.items() if k not in FUNNEL_ORDER)
    if other:
        stages.append({"stage": "other", "count": other})
    return {"stages": stages, "total": sum(c["count"] for c in stages)}

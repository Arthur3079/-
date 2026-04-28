"""Dashboard: KPI + сводка по часам."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import (
    Client,  # noqa: F401  (used in queries)
    EventLog,
    Message,
    MessageDirection,
    SaleOutcome,
    SalesAttempt,
)
from sonya.kpi.metrics import KPIEngine
from sonya_web.deps import get_session

router = APIRouter()


async def _safety_blocks_in_range(session: AsyncSession, *, start: datetime, end: datetime) -> int:
    """Кол-во `safety_reply_blocked` событий в окне [start, end)."""
    return int(
        (
            await session.execute(
                select(func.count(EventLog.id)).where(
                    EventLog.event_type == "safety_reply_blocked",
                    EventLog.timestamp >= start,
                    EventLog.timestamp < end,
                )
            )
        ).scalar_one()
        or 0
    )


async def _bounded_metrics(
    session: AsyncSession, *, start: datetime, end: datetime
) -> dict[str, float | int]:
    """Базовые KPI в окне [start, end). Используем для предыдущего окна,
    где `KPIEngine.global_metrics` не подходит — он не принимает upper bound.
    """
    active_fans = int(
        (
            await session.execute(
                select(func.count(func.distinct(Message.fan_id))).where(
                    Message.direction == MessageDirection.INCOMING,
                    Message.timestamp >= start,
                    Message.timestamp < end,
                )
            )
        ).scalar_one()
        or 0
    )
    new_fans = int(
        (
            await session.execute(
                select(func.count(Client.fan_id)).where(
                    Client.first_seen >= start,
                    Client.first_seen < end,
                )
            )
        ).scalar_one()
        or 0
    )
    msgs_in = int(
        (
            await session.execute(
                select(func.count(Message.id)).where(
                    Message.direction == MessageDirection.INCOMING,
                    Message.timestamp >= start,
                    Message.timestamp < end,
                )
            )
        ).scalar_one()
        or 0
    )
    msgs_out = int(
        (
            await session.execute(
                select(func.count(Message.id)).where(
                    Message.direction == MessageDirection.OUTGOING,
                    Message.timestamp >= start,
                    Message.timestamp < end,
                )
            )
        ).scalar_one()
        or 0
    )
    revenue = float(
        (
            await session.execute(
                select(func.coalesce(func.sum(SalesAttempt.amount_usd_equivalent), 0.0)).where(
                    SalesAttempt.outcome == SaleOutcome.PURCHASED,
                    SalesAttempt.attempted_at >= start,
                    SalesAttempt.attempted_at < end,
                )
            )
        ).scalar_one()
        or 0.0
    )
    purchases = int(
        (
            await session.execute(
                select(func.count(SalesAttempt.id)).where(
                    SalesAttempt.outcome == SaleOutcome.PURCHASED,
                    SalesAttempt.attempted_at >= start,
                    SalesAttempt.attempted_at < end,
                )
            )
        ).scalar_one()
        or 0
    )
    fans_who_purchased = int(
        (
            await session.execute(
                select(func.count(func.distinct(SalesAttempt.fan_id))).where(
                    SalesAttempt.outcome == SaleOutcome.PURCHASED,
                    SalesAttempt.attempted_at >= start,
                    SalesAttempt.attempted_at < end,
                )
            )
        ).scalar_one()
        or 0
    )
    conversion = (fans_who_purchased / active_fans) if active_fans > 0 else 0.0
    return {
        "active_fans": active_fans,
        "new_fans": new_fans,
        "total_messages_in": msgs_in,
        "total_messages_out": msgs_out,
        "total_revenue": round(revenue, 2),
        "total_purchases": purchases,
        "conversion_rate": round(conversion, 3),
    }


@router.get("/dashboard/summary")
async def dashboard_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    window_days: Annotated[int, Query(ge=1, le=365)] = 7,
) -> dict[str, object]:
    """Высокоуровневые KPI за окно + цифры за предыдущее окно для дельт."""
    metrics = await KPIEngine.global_metrics(session, window_days=window_days)
    now = datetime.now(UTC)
    safety_window_start = now - timedelta(days=window_days)
    safety_total = await _safety_blocks_in_range(session, start=safety_window_start, end=now)
    # Предыдущее окно той же длины — считаем «руками», т.к. `KPIEngine.global_metrics`
    # фильтрует только по >= start и без upper-bound подмешивает текущее окно.
    prev_window_end = safety_window_start
    prev_window_start = now - timedelta(days=2 * window_days)
    prev_metrics = await _bounded_metrics(session, start=prev_window_start, end=prev_window_end)
    prev_safety_total = await _safety_blocks_in_range(
        session,
        start=prev_window_start,
        end=prev_window_end,
    )
    return {
        "window_days": window_days,
        "total_fans": metrics.total_fans,
        "active_fans": metrics.active_fans,
        "new_fans": metrics.new_fans,
        "total_messages_in": metrics.total_messages_in,
        "total_messages_out": metrics.total_messages_out,
        "response_rate": round(metrics.response_rate, 3),
        "total_revenue": round(metrics.total_revenue, 2),
        "total_purchases": metrics.total_purchases,
        "conversion_rate": round(metrics.conversion_rate, 3),
        "avg_revenue_per_fan": round(metrics.avg_revenue_per_fan, 2),
        "churned_fans": metrics.churned_fans,
        "churn_rate": round(metrics.churn_rate, 3),
        "safety_blocks": safety_total,
        "handoff_count": metrics.handoff_count,
        "whale_count": metrics.whale_count,
        "previous": {**prev_metrics, "safety_blocks": prev_safety_total},
    }


@router.get("/dashboard/activity")
async def dashboard_activity(
    session: Annotated[AsyncSession, Depends(get_session)],
    window_days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> dict[str, object]:
    """Сообщения in/out по дням за окно — для графика."""
    now = datetime.now(UTC)
    window_start = (now - timedelta(days=window_days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    msg_rows = (
        await session.execute(
            select(Message.timestamp, Message.direction).where(Message.timestamp >= window_start)
        )
    ).all()

    by_day: dict[str, dict[str, int]] = {}
    for ts, direction in msg_rows:
        if ts is None:
            continue
        # Нормализуем к UTC-дате — SQLite-driver может вернуть naive datetime.
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        key = ts.astimezone(UTC).date().isoformat()
        bucket = by_day.setdefault(key, {"in": 0, "out": 0})
        if direction == MessageDirection.INCOMING:
            bucket["in"] += 1
        else:
            bucket["out"] += 1

    days: list[str] = []
    incoming: list[int] = []
    outgoing: list[int] = []
    for i in range(window_days):
        d = (window_start + timedelta(days=i)).date().isoformat()
        days.append(d)
        bucket = by_day.get(d, {"in": 0, "out": 0})
        incoming.append(bucket["in"])
        outgoing.append(bucket["out"])

    revenue_rows = (
        await session.execute(
            select(SalesAttempt.attempted_at, SalesAttempt.amount_usd_equivalent).where(
                SalesAttempt.attempted_at >= window_start,
                SalesAttempt.outcome == SaleOutcome.PURCHASED,
            )
        )
    ).all()
    revenue_map: dict[str, float] = {}
    for ts, amount in revenue_rows:
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        key = ts.astimezone(UTC).date().isoformat()
        revenue_map[key] = revenue_map.get(key, 0.0) + float(amount or 0)
    revenue = [round(revenue_map.get(d, 0.0), 2) for d in days]

    new_fan_rows = (
        (await session.execute(select(Client.first_seen).where(Client.first_seen >= window_start)))
        .scalars()
        .all()
    )
    new_fan_map: dict[str, int] = {}
    for ts in new_fan_rows:
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        key = ts.astimezone(UTC).date().isoformat()
        new_fan_map[key] = new_fan_map.get(key, 0) + 1
    new_fans = [new_fan_map.get(d, 0) for d in days]

    return {
        "days": days,
        "messages_in": incoming,
        "messages_out": outgoing,
        "revenue_usd": revenue,
        "new_fans": new_fans,
    }

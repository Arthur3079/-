"""Sales / payments tab: попытки, оплаты, refund."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import (
    Client,
    ContentSet,
    PaymentEvent,
    SaleOutcome,
    SalesAttempt,
)
from sonya_web.deps import get_session

router = APIRouter()


@router.get("/sales/summary")
async def sales_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    window_days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, object]:
    window_start = datetime.now(UTC) - timedelta(days=window_days)

    # Outcomes breakdown.
    rows = (
        await session.execute(
            select(SalesAttempt.outcome, func.count(SalesAttempt.id))
            .where(SalesAttempt.attempted_at >= window_start)
            .group_by(SalesAttempt.outcome)
        )
    ).all()
    by_outcome = {str(o.value if hasattr(o, "value") else o): int(c) for o, c in rows}

    # Revenue / purchases.
    revenue = float(
        (
            await session.execute(
                select(func.coalesce(func.sum(SalesAttempt.amount_usd_equivalent), 0.0)).where(
                    SalesAttempt.outcome == SaleOutcome.PURCHASED,
                    SalesAttempt.attempted_at >= window_start,
                )
            )
        ).scalar_one()
        or 0.0
    )
    purchases = int(by_outcome.get("purchased", 0))
    attempts = sum(by_outcome.values())
    conversion = purchases / attempts if attempts else 0.0

    # Top selling content sets.
    top_rows = (
        await session.execute(
            select(
                SalesAttempt.content_set_id,
                ContentSet.code,
                ContentSet.name,
                func.count(SalesAttempt.id),
                func.coalesce(func.sum(SalesAttempt.amount_usd_equivalent), 0.0),
            )
            .join(ContentSet, ContentSet.id == SalesAttempt.content_set_id, isouter=True)
            .where(
                SalesAttempt.attempted_at >= window_start,
                SalesAttempt.outcome == SaleOutcome.PURCHASED,
            )
            .group_by(SalesAttempt.content_set_id, ContentSet.code, ContentSet.name)
            .order_by(desc(func.count(SalesAttempt.id)))
            .limit(10)
        )
    ).all()
    top_content = [
        {
            "content_set_id": cs_id,
            "code": code,
            "name": name,
            "purchases": int(count),
            "revenue": round(float(total or 0), 2),
        }
        for cs_id, code, name, count, total in top_rows
    ]

    return {
        "window_days": window_days,
        "by_outcome": by_outcome,
        "purchases": purchases,
        "attempts": attempts,
        "conversion_rate": round(conversion, 3),
        "revenue_usd": round(revenue, 2),
        "top_content": top_content,
    }


@router.get("/sales/attempts")
async def list_attempts(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    outcome: str | None = None,
    fan_id: int | None = None,
) -> dict[str, object]:
    stmt = (
        select(SalesAttempt, Client)
        .join(Client, Client.fan_id == SalesAttempt.fan_id)
        .order_by(desc(SalesAttempt.attempted_at))
        .limit(limit)
    )
    if outcome:
        stmt = stmt.where(SalesAttempt.outcome == outcome)
    if fan_id is not None:
        stmt = stmt.where(SalesAttempt.fan_id == fan_id)
    rows = (await session.execute(stmt)).all()
    items = [
        {
            "id": s.id,
            "fan_id": s.fan_id,
            "display_name": c.display_name or c.first_name or c.username,
            "attempted_at": s.attempted_at.isoformat(),
            "outcome": s.outcome.value if s.outcome else None,
            "amount_stars": s.amount_stars,
            "amount_usd": round(s.amount_usd_equivalent or 0, 2),
            "grain_used": s.grain_used,
            "content_set_id": s.content_set_id,
            "message_text": s.message_text,
        }
        for s, c in rows
    ]
    return {"items": items}


@router.get("/sales/payment-events")
async def list_payment_events(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, object]:
    rows = (
        (
            await session.execute(
                select(PaymentEvent).order_by(desc(PaymentEvent.timestamp)).limit(limit)
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
            "amount_stars": e.amount_stars,
            "currency": e.currency,
            "invoice_payload": e.invoice_payload,
            "telegram_charge_id": e.telegram_charge_id,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in rows
    ]
    return {"items": items}

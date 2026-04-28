"""Клиенты (фаны): список, детальная карточка, статистика диалога,
подсказки контент-сетов и ручная отметка оплаты.

Поле ``account_id`` в ответах сейчас всегда ``"sonya-main"`` — это
плейсхолдер под будущий мультиаккаунт (ферма телеграм-аккаунтов): фронт
уже может его читать, бэкенд будет фильтровать по нему позже.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.admin import repository as admin_repo
from sonya.db.models import (
    Client,
    ContentSet,
    Fact,
    Message,
    MessageDirection,
    SaleOutcome,
    SalesAttempt,
)
from sonya_web.deps import get_session

router = APIRouter()

ACCOUNT_PLACEHOLDER = "sonya-main"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _client_brief(c: Client, *, last_msg: Message | None = None) -> dict[str, object]:
    last_active = _coerce_aware(c.last_active)
    online = "offline"
    if last_active is not None:
        ago = (_now() - last_active).total_seconds()
        if ago < 300:
            online = "online"
        elif ago < 3600:
            online = "recently"

    out: dict[str, object] = {
        "fan_id": c.fan_id,
        "account_id": ACCOUNT_PLACEHOLDER,
        "username": c.username,
        "first_name": c.first_name,
        "last_name": c.last_name,
        "display_name": c.display_name or c.first_name or c.username,
        "fan_type": c.fan_type,
        "status": c.status.value if c.status else None,
        "current_stage": c.current_stage,
        "risk_level": c.risk_level,
        "is_paused": c.is_paused,
        "handoff_required": c.handoff_required,
        "online_status": online,
        "total_spend_30d": round(c.total_spend_30d or 0.0, 2),
        "total_spend_lifetime": round(c.total_spend_lifetime or 0.0, 2),
        "ltv_estimate": round(c.ltv_estimate or 0.0, 2),
        "last_active": last_active.isoformat() if last_active else None,
        "first_seen": c.first_seen.isoformat() if c.first_seen else None,
        "last_inbound_at": c.last_inbound_at.isoformat() if c.last_inbound_at else None,
        "last_outbound_at": c.last_outbound_at.isoformat() if c.last_outbound_at else None,
        "language": c.language,
        "country_guess": c.country_guess,
    }
    if last_msg is not None:
        out["last_message_preview"] = (last_msg.content or f"[{last_msg.media_type.value}]")[:120]
        out["last_message_direction"] = last_msg.direction.value
        out["last_message_at"] = last_msg.timestamp.isoformat()
    else:
        out["last_message_preview"] = None
        out["last_message_direction"] = None
        out["last_message_at"] = None
    return out


@router.get("/clients")
async def list_clients(
    session: Annotated[AsyncSession, Depends(get_session)],
    stage: str | None = None,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    stmt = select(Client)
    if stage:
        stmt = stmt.where(Client.current_stage == stage)
    if status:
        stmt = stmt.where(Client.status == status)
    stmt = stmt.order_by(desc(Client.last_active)).offset(offset).limit(limit)
    rows = list((await session.execute(stmt)).scalars().all())

    # Подгружаем последнее сообщение по каждому фану одной выборкой (preview в списке).
    last_msgs: dict[int, Message] = {}
    if rows:
        fan_ids = [c.fan_id for c in rows]
        sub = (
            select(
                Message.fan_id.label("fan_id"),
                func.max(Message.timestamp).label("ts"),
            )
            .where(Message.fan_id.in_(fan_ids))
            .group_by(Message.fan_id)
            .subquery()
        )
        msg_rows = (
            (
                await session.execute(
                    select(Message).join(
                        sub, (Message.fan_id == sub.c.fan_id) & (Message.timestamp == sub.c.ts)
                    )
                )
            )
            .scalars()
            .all()
        )
        last_msgs = {m.fan_id: m for m in msg_rows}

    items = [_client_brief(c, last_msg=last_msgs.get(c.fan_id)) for c in rows]
    return {
        "items": items,
        "limit": limit,
        "offset": offset,
        "account_id": ACCOUNT_PLACEHOLDER,
    }


@router.get("/clients/{fan_id}")
async def get_client(
    fan_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    client = (
        await session.execute(select(Client).where(Client.fan_id == fan_id))
    ).scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail=f"Client {fan_id} not found")

    facts = (
        (
            await session.execute(
                select(Fact).where(Fact.fan_id == fan_id).order_by(desc(Fact.date_disclosed))
            )
        )
        .scalars()
        .all()
    )
    purchases = int(
        (
            await session.execute(
                select(func.count(SalesAttempt.id)).where(
                    SalesAttempt.fan_id == fan_id,
                    SalesAttempt.outcome == SaleOutcome.PURCHASED,
                )
            )
        ).scalar_one()
        or 0
    )
    last_msg = (
        await session.execute(
            select(Message)
            .where(Message.fan_id == fan_id)
            .order_by(desc(Message.timestamp))
            .limit(1)
        )
    ).scalar_one_or_none()

    base = _client_brief(client, last_msg=last_msg)
    base.update(
        {
            "flags": client.flags,
            "notes": client.notes,
            "preferred_grain": client.preferred_grain,
            "consecutive_outbound_without_reply": client.consecutive_outbound_without_reply,
            "last_offer_at": client.last_offer_at.isoformat() if client.last_offer_at else None,
            "last_purchase_at": client.last_purchase_at.isoformat()
            if client.last_purchase_at
            else None,
            "facts": [
                {
                    "key": f.key,
                    "value": f.value,
                    "confidence": f.confidence,
                    "date_disclosed": f.date_disclosed.isoformat(),
                }
                for f in facts
            ],
            "purchase_count": purchases,
        }
    )
    return base


@router.get("/clients/{fan_id}/messages")
async def list_messages(
    fan_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, object]:
    rows = (
        (
            await session.execute(
                select(Message)
                .where(Message.fan_id == fan_id)
                .order_by(desc(Message.timestamp))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    items = [
        {
            "id": m.id,
            "direction": m.direction.value,
            "media_type": m.media_type.value,
            "content": m.content,
            "timestamp": m.timestamp.isoformat(),
            "used_grain": m.used_grain,
            "used_playbook": m.used_playbook,
        }
        for m in reversed(rows)
    ]
    return {"items": items}


@router.get("/clients/{fan_id}/dialog_stats")
async def dialog_stats(
    fan_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """Сводка по диалогу для карточки фана: счётчики, среднее время ответа,
    статус «ждём ответа», эвристика «готов платить»."""

    client = (
        await session.execute(select(Client).where(Client.fan_id == fan_id))
    ).scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail=f"Client {fan_id} not found")

    now = _now()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)

    total_in = int(
        (
            await session.execute(
                select(func.count(Message.id)).where(
                    Message.fan_id == fan_id,
                    Message.direction == MessageDirection.INCOMING,
                )
            )
        ).scalar_one()
        or 0
    )
    total_out = int(
        (
            await session.execute(
                select(func.count(Message.id)).where(
                    Message.fan_id == fan_id,
                    Message.direction == MessageDirection.OUTGOING,
                )
            )
        ).scalar_one()
        or 0
    )
    cnt_24h = int(
        (
            await session.execute(
                select(func.count(Message.id)).where(
                    Message.fan_id == fan_id,
                    Message.timestamp >= last_24h,
                )
            )
        ).scalar_one()
        or 0
    )
    cnt_7d = int(
        (
            await session.execute(
                select(func.count(Message.id)).where(
                    Message.fan_id == fan_id,
                    Message.timestamp >= last_7d,
                )
            )
        ).scalar_one()
        or 0
    )

    # Среднее время ответа Sonya на входящие за последние 50 пар сообщений.
    msgs = list(
        (
            await session.execute(
                select(Message)
                .where(Message.fan_id == fan_id)
                .order_by(desc(Message.timestamp))
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    msgs.reverse()
    deltas: list[float] = []
    pending_inbound: datetime | None = None
    for m in msgs:
        ts = _coerce_aware(m.timestamp)
        if m.direction == MessageDirection.INCOMING:
            pending_inbound = ts
        elif m.direction == MessageDirection.OUTGOING and pending_inbound is not None:
            if ts is not None:
                deltas.append((ts - pending_inbound).total_seconds())
            pending_inbound = None
    avg_response_seconds = round(sum(deltas) / len(deltas), 1) if deltas else None

    # Кто ходит последним: ждём ответа фана vs ждём чтобы Sonya ответила.
    last_inbound = _coerce_aware(client.last_inbound_at)
    last_outbound = _coerce_aware(client.last_outbound_at)
    last_msg_dir = "none"
    waiting_for = "none"
    if last_inbound and last_outbound:
        if last_inbound > last_outbound:
            last_msg_dir = "incoming"
            waiting_for = "sonya"
        else:
            last_msg_dir = "outgoing"
            waiting_for = "fan"
    elif last_inbound:
        last_msg_dir = "incoming"
        waiting_for = "sonya"
    elif last_outbound:
        last_msg_dir = "outgoing"
        waiting_for = "fan"

    # Эвристика «готов платить» — по стадии и недавним офферам.
    last_offer_at = _coerce_aware(client.last_offer_at)
    last_purchase_at = _coerce_aware(client.last_purchase_at)
    stage = client.current_stage
    if stage in {"offer_pending"}:
        readiness = "high"
        readiness_reason = "офферта отправлена, ждём оплаты"
    elif stage in {"qualify"} and last_offer_at and (now - last_offer_at).days < 3:
        readiness = "high"
        readiness_reason = "интересуется, был оффер"
    elif stage in {"qualify"}:
        readiness = "medium"
        readiness_reason = "интересуется, оффер ещё не делали"
    elif stage in {"repeat_ready", "aftercare"} and last_purchase_at:
        readiness = "high"
        readiness_reason = "уже покупал — целевой повтор"
    elif stage in {"warmup"}:
        readiness = "medium"
        readiness_reason = "разогрев, рано офферить"
    elif stage in {"welcome"}:
        readiness = "low"
        readiness_reason = "только зашёл"
    elif stage in {"ghost"}:
        readiness = "low"
        readiness_reason = "не отвечает, ghost-recovery"
    else:
        readiness = "unknown"
        readiness_reason = ""

    online = "offline"
    last_active = _coerce_aware(client.last_active)
    if last_active is not None:
        ago = (now - last_active).total_seconds()
        if ago < 300:
            online = "online"
        elif ago < 3600:
            online = "recently"

    return {
        "fan_id": fan_id,
        "account_id": ACCOUNT_PLACEHOLDER,
        "messages_total": total_in + total_out,
        "messages_in": total_in,
        "messages_out": total_out,
        "messages_24h": cnt_24h,
        "messages_7d": cnt_7d,
        "avg_response_seconds": avg_response_seconds,
        "last_message_direction": last_msg_dir,
        "waiting_for": waiting_for,  # 'sonya' | 'fan' | 'none'
        "online_status": online,
        "consecutive_outbound_without_reply": client.consecutive_outbound_without_reply,
        "readiness_to_pay": readiness,  # 'high' | 'medium' | 'low' | 'unknown'
        "readiness_reason": readiness_reason,
        "last_offer_at": last_offer_at.isoformat() if last_offer_at else None,
        "last_purchase_at": last_purchase_at.isoformat() if last_purchase_at else None,
    }


@router.get("/clients/{fan_id}/suggestions")
async def suggest_content(
    fan_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=20)] = 6,
) -> dict[str, object]:
    """Подобрать контент-сеты под фана: по типу (target_types csv),
    исключаем уже купленные. Возвращаем компактный список — оператор
    решит, что предложить."""

    client = (
        await session.execute(select(Client).where(Client.fan_id == fan_id))
    ).scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail=f"Client {fan_id} not found")

    purchased_ids_raw = (
        await session.execute(
            select(SalesAttempt.content_set_id).where(
                SalesAttempt.fan_id == fan_id,
                SalesAttempt.outcome == SaleOutcome.PURCHASED,
                SalesAttempt.content_set_id.is_not(None),
            )
        )
    ).all()
    purchased_ids = {row[0] for row in purchased_ids_raw if row[0] is not None}

    sets = list(
        (
            await session.execute(
                select(ContentSet).where(ContentSet.is_active == True)  # noqa: E712
            )
        )
        .scalars()
        .all()
    )

    fan_type = (client.fan_type or "").upper()
    stage = client.current_stage

    def _score(s: ContentSet) -> tuple[int, float]:
        match = 0
        if fan_type and s.target_types:
            targets = {t.strip().upper() for t in s.target_types.split(",") if t.strip()}
            if fan_type in targets:
                match = 2
            elif fan_type[:1] in {t[:1] for t in targets if t}:
                match = 1
        # На ранних стадиях — недорогие сеты, на repeat_ready — дороже.
        price_score = -float(s.price_usd_equivalent or 0.0)
        if stage in {"repeat_ready", "aftercare"}:
            price_score = float(s.price_usd_equivalent or 0.0)
        return (match, price_score)

    candidates = sorted(
        [s for s in sets if s.id not in purchased_ids],
        key=_score,
        reverse=True,
    )

    items = [
        {
            "id": s.id,
            "code": s.code,
            "name": s.name,
            "theme": s.theme,
            "price_stars": s.price_stars,
            "price_usd": round(s.price_usd_equivalent or 0.0, 2),
            "target_types": s.target_types,
            "description": (s.description or "")[:240],
        }
        for s in candidates[:limit]
    ]
    return {
        "fan_id": fan_id,
        "account_id": ACCOUNT_PLACEHOLDER,
        "items": items,
        "fan_type": fan_type,
        "current_stage": stage,
    }


class PaymentOutcomeRequest(BaseModel):
    attempt_id: int = Field(ge=1)
    outcome: str = Field(pattern="^(purchased|declined|refunded)$")
    note: str | None = Field(default=None, max_length=240)


@router.post("/clients/{fan_id}/payment_outcome")
async def mark_payment_outcome(
    fan_id: int,
    body: PaymentOutcomeRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """Ручная отметка оператора: оплатил / не оплатил / возврат.
    Авто-приём оплат пока не подключён, оператор фиксирует факт сам.

    Записывается в `admin_actions` с типом ``payment_mark`` для аудита.
    """
    sa = (
        await session.execute(
            select(SalesAttempt).where(
                SalesAttempt.id == body.attempt_id, SalesAttempt.fan_id == fan_id
            )
        )
    ).scalar_one_or_none()
    if sa is None:
        raise HTTPException(status_code=404, detail="Sales attempt not found")

    try:
        sa.outcome = SaleOutcome(body.outcome)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Если оператор отметил «оплатил» — обновляем lifetime клиента.
    if sa.outcome == SaleOutcome.PURCHASED:
        client = (
            await session.execute(select(Client).where(Client.fan_id == fan_id))
        ).scalar_one_or_none()
        if client is not None:
            client.last_purchase_at = _now()

    payload = f"attempt={body.attempt_id} outcome={body.outcome}"
    if body.note:
        payload = f"{payload} note={body.note[:120]}"
    await admin_repo.log_action(
        session,
        admin_user_id=0,
        action_type="payment_mark",
        target_fan_id=fan_id,
        payload=payload,
    )
    await session.commit()
    return {"ok": True, "attempt_id": sa.id, "outcome": sa.outcome.value}

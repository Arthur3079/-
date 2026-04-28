"""Pure DB-side handlers for payment-bot lifecycle events.

Kept separate from `main.py` so the payment lifecycle is unit-testable
without spinning up a real Bot API process.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import (
    Client,
    ContentDelivery,
    PaymentEvent,
    SaleOutcome,
    SalesAttempt,
    SalesStatus,
)
from sonya.observability import EventType, write_event
from sonya.scheduler.repository import enqueue_followup


@dataclass
class PaymentApplied:
    """Outcome of applying a successful_payment update to the DB."""

    sales_attempt_id: int | None
    payment_event_id: int
    delivery_id: int | None


async def record_invoice_event(
    session: AsyncSession,
    *,
    fan_id: int,
    invoice_payload: str,
    amount_stars: int,
    currency: str = "XTR",
    sales_attempt_id: int | None = None,
    payload_raw: dict[str, Any] | None = None,
) -> PaymentEvent:
    """Used both when the userbot reserves an invoice and when payment_bot
    actually calls Bot API. Idempotent on `(invoice_payload, event_type)` is
    *not* enforced — we want a full audit trail of every step.
    """
    ev = PaymentEvent(
        fan_id=fan_id,
        sales_attempt_id=sales_attempt_id,
        event_type="invoice_created",
        invoice_payload=invoice_payload,
        amount_stars=amount_stars,
        currency=currency,
        payload_raw=json.dumps(payload_raw) if payload_raw is not None else None,
        timestamp=datetime.now(UTC),
    )
    session.add(ev)
    await session.flush()
    return ev


async def apply_pre_checkout(
    session: AsyncSession,
    *,
    fan_id: int,
    invoice_payload: str,
    amount_stars: int,
    currency: str = "XTR",
    payload_raw: dict[str, Any] | None = None,
) -> PaymentEvent:
    """Record that Telegram asked us to confirm the cart. Always log it."""
    ev = PaymentEvent(
        fan_id=fan_id,
        sales_attempt_id=await _resolve_attempt_id(session, invoice_payload),
        event_type="pre_checkout",
        invoice_payload=invoice_payload,
        amount_stars=amount_stars,
        currency=currency,
        payload_raw=json.dumps(payload_raw) if payload_raw is not None else None,
        timestamp=datetime.now(UTC),
    )
    session.add(ev)
    await session.flush()
    return ev


async def apply_successful_payment(
    session: AsyncSession,
    *,
    fan_id: int,
    invoice_payload: str,
    amount_stars: int,
    currency: str = "XTR",
    telegram_charge_id: str | None = None,
    provider_charge_id: str | None = None,
    payload_raw: dict[str, Any] | None = None,
) -> PaymentApplied:
    """Mark the matching sales attempt PURCHASED, log event, queue delivery."""
    attempt_id = await _resolve_attempt_id(session, invoice_payload)
    content_set_id: int | None = None
    if attempt_id is not None:
        attempt = await session.get(SalesAttempt, attempt_id)
        if attempt is not None:
            attempt.outcome = SaleOutcome.PURCHASED
            attempt.amount_stars = amount_stars
            content_set_id = attempt.content_set_id
            await session.flush()

    ev = PaymentEvent(
        fan_id=fan_id,
        sales_attempt_id=attempt_id,
        event_type="successful",
        invoice_payload=invoice_payload,
        telegram_charge_id=telegram_charge_id,
        provider_charge_id=provider_charge_id,
        amount_stars=amount_stars,
        currency=currency,
        payload_raw=json.dumps(payload_raw) if payload_raw is not None else None,
        timestamp=datetime.now(UTC),
    )
    session.add(ev)
    await session.flush()

    # Bump fan lifetime spend + lifecycle bookkeeping.
    client = await session.get(Client, fan_id)
    if client is not None:
        # Stars accounting: store stars-as-stars in the count field. Operators
        # who care about USD can multiply by their conversion rate offline.
        client.total_spend_lifetime = float(client.total_spend_lifetime or 0) + float(amount_stars)
        client.total_spend_30d = float(client.total_spend_30d or 0) + float(amount_stars)
        if client.sales_status == SalesStatus.ACTIVE:
            client.sales_status = SalesStatus.ACTIVE  # no-op; future: BUYER bucket
        now = datetime.now(UTC)
        client.last_purchase_at = now
        client.last_active = now
        client.consecutive_outbound_without_reply = 0
        await session.flush()
    await write_event(
        session,
        fan_id=fan_id,
        event_type=EventType.PURCHASE_RECORDED,
        payload={
            "amount_stars": amount_stars,
            "currency": currency,
            "sales_attempt_id": attempt_id,
            "telegram_charge_id": telegram_charge_id,
        },
    )

    delivery: ContentDelivery | None = None
    if content_set_id is not None:
        delivery = ContentDelivery(
            fan_id=fan_id,
            sales_attempt_id=attempt_id,
            content_set_id=content_set_id,
            delivered_at=datetime.now(UTC),
            delivery_status="pending",  # actual file send happens in the userbot
        )
        session.add(delivery)
        await session.flush()

    # Layer 5: auto-aftercare. Queue a thank-you ping (24h) and a check-in
    # (3d) so the fan hears from us after a successful payment without an
    # operator scheduling it manually. `enqueue_followup(idempotent=True)`
    # protects against a duplicate webhook firing twice for the same
    # invoice — second call updates the existing row instead of creating
    # a duplicate.
    now = datetime.now(UTC)
    for type_, delta in (
        ("aftercare_thanks", timedelta(hours=24)),
        ("aftercare_checkin", timedelta(days=3)),
    ):
        await enqueue_followup(
            session,
            fan_id=fan_id,
            type_=type_,
            scheduled_at=now + delta,
            note=f"auto-after:{invoice_payload}",
        )

    return PaymentApplied(
        sales_attempt_id=attempt_id,
        payment_event_id=int(ev.id),
        delivery_id=int(delivery.id) if delivery is not None else None,
    )


async def _resolve_attempt_id(session: AsyncSession, payload: str) -> int | None:
    res = await session.execute(
        select(SalesAttempt.id).where(SalesAttempt.invoice_payload == payload)
    )
    row = res.first()
    return int(row[0]) if row is not None else None

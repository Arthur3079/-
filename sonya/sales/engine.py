"""High-level sales API the dialogue layer uses.

Dialogue flow when fan asks for content / hints intent CONTENT_REQUEST or
PRICE_QUESTION:

    1. `build_recommendation(...)` → picks best ContentSet + drafts copy.
    2. Sonya sends the copy + a CTA pointing the fan to the payment_bot
       (`@<pay_bot_username>`).
    3. The payment_bot picks up `payment_requests` queue and creates a real
       Telegram Stars invoice. (`payment_bot.invoices`)
    4. On `successful_payment`, payment_bot writes a `PaymentEvent` and a
       `ContentDelivery` row, and pings the userbot to actually deliver.

If `Settings.pay_bot_token` is empty, the engine still drafts the recommend
copy but logs `would create invoice for ...` instead of trying to bridge —
this is the explicit "DRY" path required by the spec (don't fake payments).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.config import Settings
from sonya.crm.repository import mark_offer_sent
from sonya.db.models import ContentSet, PaymentEvent, SaleOutcome, SalesAttempt
from sonya.sales.recommend import recommend_for_fan

if TYPE_CHECKING:  # pragma: no cover
    # Type-only import to avoid: dialogue.service imports sales.engine, and
    # sales.engine would otherwise need to import from the partially-loaded
    # sonya.dialogue package.
    from sonya.dialogue.intent import Intent


@dataclass
class RecommendOutcome:
    """One recommendation ready to send."""

    content_set: ContentSet
    copy: str
    invoice_payload: str  # opaque token; payment_bot uses it as Telegram payload
    cta: str  # CTA text appended to the message; e.g. "@sonya_pay_bot /buy <code>"
    dry_run: bool


_OFFER_INTENT_VALUES: frozenset[str] = frozenset(
    {"content_request", "price_question", "payment_question"}
)


async def build_recommendation(
    session: AsyncSession,
    *,
    fan_id: int,
    intent: Intent,
    fan_type_lite: str | None,
    fan_type_fine: str | None,
    settings: Settings,
) -> RecommendOutcome | None:
    """Decide whether to offer; if yes, draft copy and reserve a payload token."""
    if intent.value not in _OFFER_INTENT_VALUES:
        return None

    candidates = await recommend_for_fan(
        session,
        fan_id=fan_id,
        fan_type_lite=fan_type_lite,
        fan_type_fine=fan_type_fine,
        limit=1,
    )
    if not candidates:
        return None
    cs = candidates[0]

    payload = _make_payload(fan_id=fan_id, content_set_id=cs.id or 0)
    copy = _draft_copy(cs)
    cta = _draft_cta(cs, settings=settings, payload=payload)

    dry_run = not settings.pay_bot_token
    if dry_run:
        logger.info(
            "Sales DRY: would create invoice for fan={} set={} payload={}",
            fan_id,
            cs.code,
            payload,
        )

    # Persist the *intent* to sell as a SalesAttempt(OFFERED). The actual
    # successful sale gets a separate PURCHASED row when payment lands.
    session.add(
        SalesAttempt(
            fan_id=fan_id,
            content_set_id=cs.id,
            attempted_at=datetime.now(UTC),
            outcome=SaleOutcome.SENT,
            amount_stars=cs.price_stars,
            amount_usd_equivalent=cs.price_usd_equivalent,
            invoice_payload=payload,
            grain_used=None,
            message_text=copy,
        )
    )
    await session.flush()

    # Stamp the fan with the offer time so CadenceEngine can enforce
    # the OFFER_COOLDOWN window on subsequent turns. Also writes an
    # `offer_sent` row in events_log via the repository.
    await mark_offer_sent(session, fan_id=fan_id)

    return RecommendOutcome(
        content_set=cs, copy=copy, invoice_payload=payload, cta=cta, dry_run=dry_run
    )


async def register_invoice_request(
    session: AsyncSession,
    *,
    fan_id: int,
    invoice_payload: str,
    sales_attempt_id: int | None = None,
    amount_stars: int = 0,
    currency: str = "XTR",
) -> PaymentEvent:
    """Log that we *asked* the payment_bot to send an invoice."""
    ev = PaymentEvent(
        fan_id=fan_id,
        sales_attempt_id=sales_attempt_id,
        event_type="invoice_created",
        invoice_payload=invoice_payload,
        amount_stars=amount_stars,
        currency=currency,
        timestamp=datetime.now(UTC),
    )
    session.add(ev)
    await session.flush()
    return ev


def _make_payload(*, fan_id: int, content_set_id: int) -> str:
    nonce = secrets.token_hex(6)
    return f"sonya:{fan_id}:{content_set_id}:{nonce}"


def _draft_copy(cs: ContentSet) -> str:
    """Light fallback copy. Real PPV-копи lives in knowledge."""
    name = cs.name.replace("_", " ")
    if cs.price_stars:
        return f"got something for you 💜 — '{name}'. {cs.price_stars}⭐ if you want it."
    return f"got something for you 💜 — '{name}'."


def _draft_cta(cs: ContentSet, *, settings: Settings, payload: str) -> str:
    bot = settings.pay_bot_username or "sonya_pay_bot"
    return f"to grab it: @{bot}\nuse: /buy {cs.code}"

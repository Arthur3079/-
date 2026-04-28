"""Entrypoint for the standalone payment bot process.

Run as: `python -m sonya.payment_bot.main`. Reads `PAY_BOT_TOKEN` from .env;
exits with a clear message if the token is missing (so you can run Sonya
without a payment bot in dev / DRY_RUN).
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from loguru import logger

from sonya.config import get_settings
from sonya.db.session import async_session_factory
from sonya.payment_bot.bot_api import BotApi, long_poll
from sonya.payment_bot.handlers import (
    apply_pre_checkout,
    apply_successful_payment,
)


async def _on_update(api: BotApi, factory: Any, upd: dict[str, Any]) -> None:
    """Dispatch one update."""
    if "pre_checkout_query" in upd:
        q = upd["pre_checkout_query"]
        await _handle_pre_checkout(api, factory, q)
        return
    if "message" in upd and "successful_payment" in upd["message"]:
        msg = upd["message"]
        await _handle_successful_payment(factory, msg)
        return
    # All other updates (commands like /start, /buy CODE) are out of scope for
    # this MVP; the user-facing copy lives in the Sonya userbot.


async def _handle_pre_checkout(api: BotApi, factory: Any, q: dict[str, Any]) -> None:
    payload = str(q.get("invoice_payload") or "")
    fan_id = int(q.get("from", {}).get("id") or 0)
    amount_stars = int(q.get("total_amount") or 0)
    currency = str(q.get("currency") or "XTR")
    async with factory() as session, session.begin():
        await apply_pre_checkout(
            session,
            fan_id=fan_id,
            invoice_payload=payload,
            amount_stars=amount_stars,
            currency=currency,
            payload_raw=q,
        )
    try:
        await api.answer_pre_checkout_query(pre_checkout_query_id=str(q["id"]), ok=True)
    except Exception:
        logger.opt(exception=True).error(
            "Failed to answer pre_checkout_query (payload={})", payload
        )


async def _handle_successful_payment(factory: Any, msg: dict[str, Any]) -> None:
    sp = msg["successful_payment"]
    fan_id = int(msg.get("from", {}).get("id") or 0)
    payload = str(sp.get("invoice_payload") or "")
    amount_stars = int(sp.get("total_amount") or 0)
    currency = str(sp.get("currency") or "XTR")
    telegram_charge_id = sp.get("telegram_payment_charge_id")
    provider_charge_id = sp.get("provider_payment_charge_id")
    async with factory() as session, session.begin():
        applied = await apply_successful_payment(
            session,
            fan_id=fan_id,
            invoice_payload=payload,
            amount_stars=amount_stars,
            currency=currency,
            telegram_charge_id=telegram_charge_id,
            provider_charge_id=provider_charge_id,
            payload_raw=msg,
        )
    logger.info(
        "successful_payment fan={} attempt={} delivery={} stars={}",
        fan_id,
        applied.sales_attempt_id,
        applied.delivery_id,
        amount_stars,
    )


async def _amain() -> int:
    settings = get_settings()
    if not settings.pay_bot_token:
        logger.error(
            "PAY_BOT_TOKEN is empty. Set it in .env to run the payment bot.\n"
            "(Sonya will run without it, but in DRY mode for sales.)"
        )
        return 2
    api = BotApi(settings.pay_bot_token)
    factory = async_session_factory()
    logger.info("Payment bot starting (long-polling)")
    try:
        await long_poll(
            api,
            on_update=lambda u: _on_update(api, factory, u),
            allowed_updates=["pre_checkout_query", "message"],
        )
    finally:
        await api.aclose()
    return 0


def run() -> None:
    """Console-script entrypoint."""
    sys.exit(asyncio.run(_amain()))


if __name__ == "__main__":
    run()

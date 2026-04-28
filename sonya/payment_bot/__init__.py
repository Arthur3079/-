"""Separate Telegram Bot API process that handles Telegram Stars payments.

Why split it out: a userbot (Telethon, MTProto with a user account) **cannot**
send invoices or accept Stars — only Bot API bots can. So the architecture is:

    Sonya userbot (sonya.main)              Payment bot (sonya.payment_bot.main)
    ----------------------------            -----------------------------------
    decides to offer content      ───►      sendInvoice(fan, set, payload)
    drafts CTA → @sonya_pay_bot
                                  ◄───      pre_checkout_query → answerOk
                                  ◄───      successful_payment → record + deliver

Both processes share the same SQLite/Postgres database. The payment bot only
ever writes `payment_events`, `content_deliveries`, and updates the matching
`sales_attempts` row to PURCHASED.

If `PAY_BOT_TOKEN` is unset, `main` exits with a helpful message instead of
crashing — Sonya's sales engine still produces recommend copy, just without
real Stars charging.
"""

from sonya.payment_bot.bot_api import BotApi, BotApiError
from sonya.payment_bot.handlers import (
    apply_pre_checkout,
    apply_successful_payment,
    record_invoice_event,
)

__all__ = [
    "BotApi",
    "BotApiError",
    "apply_pre_checkout",
    "apply_successful_payment",
    "record_invoice_event",
]

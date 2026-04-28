"""Wrappers around Telethon I/O that survive FloodWait and transient RPC errors.

Every outbound action (send a message, set typing) goes through these helpers
so that the handler never sees a raw `FloodWaitError` and we get one place to
log/measure rate-limit pressure.

Strategy:
- On `FloodWaitError`: sleep `seconds + small jitter`, retry once. If the wait
  is absurd (>120s by default) — abort and let caller decide (typically:
  log + skip this reply). This avoids hanging the whole process for a
  Telegram-side cooldown.
- On `RPCError`: one short retry with backoff.
- All errors are logged with structured fields (action, fan/chat hint).
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from loguru import logger
from telethon.errors import FloodWaitError, RPCError

DEFAULT_MAX_FLOOD_WAIT_SECONDS = 120.0
DEFAULT_RPC_BACKOFF_SECONDS = 1.5


async def safe_respond(
    event: Any,
    reply_text: str,
    *,
    max_flood_wait: float = DEFAULT_MAX_FLOOD_WAIT_SECONDS,
    chat_hint: str | None = None,
) -> Any | None:
    """Send a reply with FloodWait/RPCError handling.

    Returns the sent message object, or None if the send was skipped due to
    an unrecoverable rate-limit / transient error.
    """
    label = chat_hint or _chat_hint_from_event(event)
    try:
        return await event.respond(reply_text)
    except FloodWaitError as e:
        wait = float(getattr(e, "seconds", 0) or 0)
        if wait > max_flood_wait:
            logger.warning(
                "Telegram FloodWait too long ({}s > {}s); skipping respond to {}",
                wait,
                max_flood_wait,
                label,
            )
            return None
        jitter = random.uniform(0.5, 1.5)
        logger.warning(
            "Telegram FloodWait on respond to {}: sleeping {:.1f}s (+jitter {:.1f}s)",
            label,
            wait,
            jitter,
        )
        await asyncio.sleep(wait + jitter)
        try:
            return await event.respond(reply_text)
        except RPCError as e2:
            logger.error("Telegram respond retry failed for {}: {}", label, e2)
            return None
    except RPCError as e:
        logger.warning(
            "Telegram RPCError on respond to {}: {}; retrying once",
            label,
            e,
        )
        await asyncio.sleep(DEFAULT_RPC_BACKOFF_SECONDS)
        try:
            return await event.respond(reply_text)
        except RPCError as e2:
            logger.error("Telegram respond retry failed for {}: {}", label, e2)
            return None


class safe_typing_action:
    """Async context manager wrapping `client.action(chat, "typing")`.

    Eats FloodWait/RPC errors silently — typing is a nice-to-have, never worth
    breaking the actual reply for. If the typing action can't be acquired we
    yield anyway so the caller's logic continues normally.
    """

    def __init__(self, event: Any, *, chat_hint: str | None = None) -> None:
        self._event = event
        self._label = chat_hint or _chat_hint_from_event(event)
        self._action_cm: Any | None = None

    async def __aenter__(self) -> safe_typing_action:
        try:
            self._action_cm = self._event.client.action(self._event.chat_id, "typing")
            await self._action_cm.__aenter__()
        except FloodWaitError as e:
            logger.debug(
                "Skipping typing indicator for {} (FloodWait {}s)",
                self._label,
                getattr(e, "seconds", "?"),
            )
            self._action_cm = None
        except RPCError as e:
            logger.debug("Skipping typing indicator for {}: {}", self._label, e)
            self._action_cm = None
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._action_cm is None:
            return
        try:
            await self._action_cm.__aexit__(exc_type, exc, tb)
        except RPCError as e:
            logger.debug("Typing indicator close errored for {}: {}", self._label, e)


def _chat_hint_from_event(event: Any) -> str:
    """Best-effort string for log lines (chat_id / sender_id / username)."""
    chat_id = getattr(event, "chat_id", None)
    sender_id = getattr(event, "sender_id", None)
    if chat_id and sender_id and chat_id != sender_id:
        return f"chat={chat_id} sender={sender_id}"
    if sender_id:
        return f"sender={sender_id}"
    if chat_id:
        return f"chat={chat_id}"
    return "<unknown>"

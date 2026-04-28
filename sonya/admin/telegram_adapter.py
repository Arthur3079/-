"""Telethon adapter that wires `dispatch_command` to the admin chat.

The handler is **scoped** to messages from `settings.admin_user_ids`. Anyone
else who DMs the userbot lands in the regular `sonya.telegram.handlers`
pipeline. The admin handler runs first and short-circuits if the sender is
allowed and the text starts with `/`.
"""

from __future__ import annotations

from loguru import logger
from telethon import TelegramClient, events
from telethon.tl.types import User

from sonya.admin.commands import dispatch_command
from sonya.config import Settings
from sonya.db.session import async_session_factory
from sonya.knowledge import KnowledgeIndex
from sonya.runtime import safe_respond


def register_admin_handlers(
    client: TelegramClient,
    settings: Settings,
    *,
    knowledge: KnowledgeIndex | None = None,
) -> None:
    """Attach a NewMessage handler for admin commands.

    No-op (with a warning) if `settings.admin_user_ids` is empty — running an
    open admin chat would let anyone pause the bot.
    """
    if not settings.admin_user_ids:
        logger.warning("Admin handlers not registered: ADMIN_USER_IDS is empty in settings.")
        return

    allowed: frozenset[int] = frozenset(settings.admin_user_ids)
    logger.info("Admin handlers registered for user_ids={}", sorted(allowed))

    @client.on(events.NewMessage(incoming=True))
    async def _on_admin_message(event: events.NewMessage.Event) -> None:
        sender = await event.get_sender()
        if not isinstance(sender, User):
            return
        if sender.id not in allowed:
            return  # delegate to regular fan handler
        text = (event.raw_text or "").strip()
        if not text.startswith("/"):
            return  # not a command — let the fan handler deal with it (rare path)

        factory = async_session_factory()
        async with factory() as session, session.begin():
            result = await dispatch_command(
                session,
                admin_user_id=sender.id,
                raw_text=text,
                settings=settings,
                knowledge=knowledge,
            )

        # Telegram caps a single message at 4096 chars.
        chunks = _chunk(result.text, 3800)
        for chunk in chunks:
            await safe_respond(
                event,
                f"```\n{chunk}\n```" if "\n" in chunk else chunk,
                max_flood_wait=settings.telegram_max_flood_wait_seconds,
            )

        # Stop further handlers (don't run the fan dialogue pipeline on /commands).
        raise events.StopPropagation


def _chunk(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    parts: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= size:
            parts.append(remaining)
            break
        cut = remaining.rfind("\n", 0, size)
        if cut <= 0:
            cut = size
        parts.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    return parts

"""Оркестратор одного хода переписки.

`generate_reply` — главная точка входа. Принимает входящее сообщение, тащит
последние N сообщений из БД, склеивает промт, вызывает LLM, возвращает текст.
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.config import Settings
from sonya.db.models import Client, Message, MessageDirection
from sonya.llm.backend import LLMBackend
from sonya.llm.client import ChatMessage
from sonya.llm.prompts import (
    CLIENT_CARD_SEPARATOR,
    SYSTEM_PROMPT_BASE,
    build_system_prompt,
    render_client_card,
)


async def fetch_history(session: AsyncSession, *, fan_id: int, limit: int) -> list[Message]:
    """Последние `limit` сообщений с фаном, в порядке возрастания timestamp."""
    stmt = (
        select(Message)
        .where(Message.fan_id == fan_id)
        .order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(reversed(rows))


def history_to_chat_messages(history: list[Message]) -> list[ChatMessage]:
    """Преобразовать историю в формат chat completions."""
    out: list[ChatMessage] = []
    for m in history:
        if not m.content:
            continue
        role: str = "user" if m.direction is MessageDirection.INCOMING else "assistant"
        out.append(ChatMessage(role=role, content=m.content))  # type: ignore[arg-type]
    return out


async def generate_reply(
    *,
    backend: LLMBackend,
    settings: Settings,
    session: AsyncSession,
    client: Client,
) -> str:
    """Сгенерировать ответ Сони этому фану на последнее входящее.

    Заранее предполагаем: входящее сообщение уже сохранено в БД хендлером.
    """
    fan_label = client.known_name or client.display_name or client.username or str(client.fan_id)
    logger.info(
        "Building reply for fan_id={} (name='{}' archetype={} status={} lang={} notes={})",
        client.fan_id,
        fan_label,
        client.fan_type or "—",
        client.status.value if client.status else "—",
        client.language or settings.default_language,
        bool(client.notes),
    )

    history = await fetch_history(session, fan_id=client.fan_id, limit=settings.llm_history_limit)
    chat = history_to_chat_messages(history)
    incoming_count = sum(1 for m in chat if m.role == "user")
    outgoing_count = sum(1 for m in chat if m.role == "assistant")
    logger.info(
        "  history: {} msgs (in={} out={}, limit={})",
        len(chat),
        incoming_count,
        outgoing_count,
        settings.llm_history_limit,
    )

    card = render_client_card(client)
    if card:
        logger.info("  client card ({} chars):", len(card))
        for line in card.splitlines():
            logger.info("    | {}", line)
    else:
        logger.info("  client card: empty (no facts known yet)")

    system_prompt = build_system_prompt(client_card=card or None)
    base_chars = len(SYSTEM_PROMPT_BASE)
    sep_chars = len(CLIENT_CARD_SEPARATOR) if card else 0
    card_chars = len(card)
    logger.info(
        "  system prompt: {} chars (base={} + sep={} + card={})",
        len(system_prompt),
        base_chars,
        sep_chars,
        card_chars,
    )

    messages: list[ChatMessage] = [ChatMessage(role="system", content=system_prompt), *chat]
    return await backend.generate(messages, fan_id=client.fan_id)

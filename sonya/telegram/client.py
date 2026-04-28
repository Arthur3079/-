"""Обёртка над Telethon-клиентом.

Хранит синглтон-клиент, делает интерактивную авторизацию по номеру при первом
запуске (Telethon сам спрашивает SMS-код через `input()`), потом сессия
сохраняется в `<session_name>.session` рядом с проектом и заново код не нужен.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from telethon import TelegramClient

from sonya.config import Settings


class TelegramCredentialsMissing(RuntimeError):
    """Поднимается если в .env не заполнены ключи / номер."""


def build_client(settings: Settings, *, session_dir: Path | None = None) -> TelegramClient:
    """Создать незапущенный TelegramClient. Запуск (и авторизация) — отдельно."""
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise TelegramCredentialsMissing(
            "TELEGRAM_API_ID и TELEGRAM_API_HASH должны быть заданы в .env. "
            "Получить можно бесплатно на https://my.telegram.org/apps"
        )
    if not settings.telegram_phone:
        raise TelegramCredentialsMissing(
            "TELEGRAM_PHONE должен быть задан в .env (формат +7XXXXXXXXXX). "
            "На первом запуске Telegram пришлёт SMS-код, его впишешь в консоли."
        )

    base = session_dir or settings.project_root
    session_path = base / settings.telegram_session_name

    return TelegramClient(
        session=str(session_path),
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        device_model="Sonya",
        system_version="userbot",
        app_version="0.1.0",
        lang_code=settings.default_language,
    )


async def start_client(client: TelegramClient, settings: Settings) -> None:
    """Авторизоваться. Если сессии ещё нет — Telethon интерактивно попросит SMS-код."""
    logger.info("Starting Telegram client (phone={})...", settings.telegram_phone)
    await client.start(phone=settings.telegram_phone)
    me = await client.get_me()
    logger.success(
        "Telegram client connected as: id={} username=@{} name={}",
        me.id,
        me.username,
        getattr(me, "first_name", None),
    )

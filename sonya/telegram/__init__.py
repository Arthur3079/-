"""Telegram-userbot слой (Telethon).

MVP-1: подключение, авторизация, обработка входящих ЛС, эхо-заглушка.
"""

from sonya.telegram.client import (
    TelegramCredentialsMissing,
    build_client,
    start_client,
)
from sonya.telegram.handlers import register_handlers

__all__ = [
    "TelegramCredentialsMissing",
    "build_client",
    "register_handlers",
    "start_client",
]

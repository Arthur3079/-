"""Программный прогон Alembic-миграций при старте приложения.

Это убирает ручной шаг `alembic upgrade head` для свежей разработки и
гарантирует, что таблицы существуют до того как Telethon начнёт
обрабатывать входящие сообщения.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from loguru import logger

from sonya.config import get_settings


def _async_to_sync_url(url: str) -> str:
    return (
        url.replace("+aiosqlite", "")
        .replace("+asyncpg", "+psycopg")
        .replace("+asyncmy", "+pymysql")
    )


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def upgrade_to_head() -> None:
    """Накатить все миграции до head. Идемпотентно — если БД уже на head, no-op."""
    root = _project_root()
    ini_path = root / "alembic.ini"
    if not ini_path.exists():
        logger.warning("alembic.ini не найден в {}, миграции пропущены.", root)
        return

    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(root / "migrations"))
    settings = get_settings()
    cfg.set_main_option("sqlalchemy.url", _async_to_sync_url(settings.database_url))

    logger.info("Running alembic upgrade head ...")
    command.upgrade(cfg, "head")
    logger.info("DB migrations applied.")

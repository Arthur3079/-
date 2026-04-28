"""Точка входа.

MVP-0: проверка окружения и БД.
MVP-1: + Telegram userbot (Telethon), эхо-заглушка для входящих ЛС.
"""

from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy import text

from sonya import __version__
from sonya.admin.telegram_adapter import register_admin_handlers
from sonya.config import get_settings
from sonya.db.migrate import upgrade_to_head
from sonya.db.session import async_session_factory, get_engine
from sonya.knowledge import KnowledgeIndex, load_chunks
from sonya.llm import LLMNotConfigured, build_backend
from sonya.logging_setup import setup_logging
from sonya.scheduler import SchedulerService
from sonya.telegram import (
    TelegramCredentialsMissing,
    build_client,
    register_handlers,
    start_client,
)


def _resolve_provider_key(settings) -> str | None:  # type: ignore[no-untyped-def]
    """Вернуть ключ, который нужен для текущего LLM_PROVIDER (или None)."""
    provider = settings.llm_provider.lower()
    if provider == "gemini":
        return settings.gemini_api_key
    return settings.effective_llm_api_key


def _mask_key(key: str | None) -> str:
    if not key:
        return "<not set>"
    if len(key) <= 12:
        return key[:4] + "…"
    return f"{key[:8]}…{key[-4:]}"


def _log_config_summary(settings) -> None:  # type: ignore[no-untyped-def]
    """Один аккуратный блок: что приложение знает о себе на старте."""
    logger.info("=" * 60)
    logger.info("Config:")
    logger.info("  log_level      = {}", settings.log_level)
    logger.info("  database_url   = {}", settings.database_url)
    logger.info("  default_lang   = {}", settings.default_language)
    logger.info("  timezone       = {}", settings.sonya_timezone)
    logger.info("  humanizer      = {}", settings.enable_humanizer)
    logger.info("  dry_run        = {}", settings.dry_run)
    logger.info("  project_root   = {}", settings.project_root)
    logger.info("  knowledge_dir  = {}", settings.knowledge_dir)
    logger.info("  log_dir        = {}", settings.log_dir)
    logger.info("LLM config:")
    logger.info("  provider       = {}", settings.llm_provider)
    logger.info("  max_tokens     = {}", settings.llm_max_tokens)
    logger.info("  temperature    = {}", settings.llm_temperature)
    logger.info("  history_limit  = {} msgs", settings.llm_history_limit)
    if settings.llm_provider.lower() == "gemini":
        logger.info("  gemini_api_key = {}", _mask_key(settings.gemini_api_key))
        logger.info("  gemini_model   = {}", settings.gemini_model)
        logger.info("  thinking_level = {}", settings.gemini_thinking_level or "<off>")
        logger.info(
            "  ⚠ Gemini имеет встроенный NSFW-фильтр. Для OFM-флёрта в случае "
            "блокировок переключайся на LLM_PROVIDER=openai_compat (Hermes/Dolphin)."
        )
    else:
        logger.info("  api_key        = {}", _mask_key(settings.effective_llm_api_key))
        logger.info("  base_url       = {}", settings.llm_base_url)
        logger.info("  model          = {}", settings.llm_model)
    logger.info("Telegram:")
    logger.info("  api_id         = {}", settings.telegram_api_id or "<not set>")
    logger.info("  phone          = {}", settings.telegram_phone or "<not set>")
    logger.info("  session_name   = {}", settings.telegram_session_name)
    logger.info("=" * 60)


def _build_knowledge_index(settings) -> KnowledgeIndex | None:  # type: ignore[no-untyped-def]
    """Загрузить markdown-базу в память. Возвращает None если директория пуста."""
    if not settings.knowledge_dir.exists():
        logger.info("Knowledge dir не существует: {}", settings.knowledge_dir)
        return None
    chunks, stats = load_chunks(settings.knowledge_dir)
    if not chunks:
        logger.info(
            "Knowledge dir пуст или не содержит .md: {}",
            settings.knowledge_dir,
        )
        return None
    logger.info(
        "Knowledge index: {} chunks from {}/{} markdown files ({} chars total)",
        stats.chunks,
        stats.files_indexed,
        stats.files_scanned,
        stats.total_chars,
    )
    return KnowledgeIndex(chunks)


async def health_check() -> None:
    """Проверяем, что БД доступна и движок поднимается."""
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
    factory = async_session_factory()
    async with factory() as session:
        await session.execute(text("SELECT 1"))
    logger.info("DB healthcheck passed.")


async def amain() -> None:
    setup_logging()
    settings = get_settings()
    logger.info("Sonya v{} starting up", __version__)
    _log_config_summary(settings)
    knowledge = _build_knowledge_index(settings)

    # Накатываем миграции до старта Telegram-клиента, чтобы handlers не падали
    # на пустой БД ("no such table: clients").
    try:
        await asyncio.to_thread(upgrade_to_head)
    except Exception:
        logger.exception(
            "Alembic upgrade failed; aborting startup so we don't run against a broken schema."
        )
        raise

    await health_check()

    backend = None
    provider_key = _resolve_provider_key(settings)
    if provider_key:
        try:
            backend = build_backend(settings)
            logger.success(
                "LLM backend ready (provider={}, model={}, endpoint={}, key={})",
                settings.llm_provider,
                backend.model,
                backend.endpoint,
                _mask_key(provider_key),
            )
        except LLMNotConfigured as e:
            logger.error("LLM-клиент не сконфигурирован: {}", e)
    else:
        logger.warning(
            "Ключ для LLM_PROVIDER={!r} не задан — Соня будет отвечать заглушкой "
            "[stub]. Заполни LLM_API_KEY (для openai_compat) или GEMINI_API_KEY "
            "(для gemini) в .env.",
            settings.llm_provider,
        )

    try:
        if not settings.telegram_api_id:
            logger.warning(
                "TELEGRAM_API_ID не задан — Telegram-клиент не стартует. "
                "Заполни TELEGRAM_API_ID/HASH/PHONE в .env, чтобы Соня вошла в аккаунт."
            )
            logger.success("Sonya is ready (no-Telegram mode).")
            return

        try:
            client = build_client(settings)
        except TelegramCredentialsMissing as e:
            logger.error("Telegram-клиент не запущен: {}", e)
            return

        # Admin handler is registered FIRST so it short-circuits on
        # `/commands` from operator IDs before the fan dialogue handler runs.
        register_admin_handlers(client, settings, knowledge=knowledge)
        register_handlers(client, settings, backend=backend, knowledge=knowledge)

        scheduler = SchedulerService(
            session_factory=async_session_factory(),
            send=lambda fan_id, text, type_: _scheduler_send(client, settings, fan_id, text),
        )
        scheduler.start()

        await start_client(client, settings)
        if settings.dry_run:
            logger.warning(
                "DRY_RUN=true — входящие логируются и пишутся в БД, но Соня НЕ отвечает. "
                "Поставь DRY_RUN=false в .env, чтобы включить отправку ответов."
            )
        logger.success("Sonya is online. Listening for incoming PMs. Ctrl+C to stop.")
        try:
            await client.run_until_disconnected()
        finally:
            scheduler.shutdown()
    finally:
        if backend is not None:
            await backend.aclose()


async def _scheduler_send(client, settings, fan_id: int, text: str) -> bool:  # type: ignore[no-untyped-def]
    """Adapter so the scheduler can send a followup via the userbot."""
    if settings.dry_run:
        logger.info("[scheduler dry] would send to {} : {!r}", fan_id, text)
        return True
    try:
        await client.send_message(fan_id, text)
        return True
    except Exception:
        logger.opt(exception=True).warning("Scheduler send to {} failed", fan_id)
        return False


def run() -> None:
    """Sync-обёртка для console_scripts entrypoint."""
    asyncio.run(amain())


if __name__ == "__main__":
    run()

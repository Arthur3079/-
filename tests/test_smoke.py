"""Smoke-тесты MVP-0: проверяем, что пакет импортится, конфиг грузится, БД работает."""

from __future__ import annotations

import pytest
from sqlalchemy import text


def test_package_imports() -> None:
    import sonya
    from sonya import config, logging_setup, main  # noqa: F401
    from sonya.db import base, models, session  # noqa: F401

    assert sonya.__version__


def test_settings_defaults() -> None:
    from sonya.config import Settings

    s = Settings(_env_file=None)  # игнорим .env, проверяем дефолты
    assert s.default_language == "en"
    assert s.sonya_timezone == "Europe/Madrid"
    assert s.enable_humanizer is True
    assert s.dry_run is True


def test_settings_empty_strings_in_env_fall_back_to_defaults(tmp_path) -> None:
    """Пустые значения в .env должны игнорироваться и фолбэчить на дефолты.

    Проверяем оба случая:
    - Optional-поля (telegram_api_id, llm_api_key) должны стать None.
    - Не-Optional поля (log_level, default_language) должны сохранить declared default,
      а не упасть на 'None is not a valid str'.
    """
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_API_ID=\nTELEGRAM_API_HASH=\nLLM_API_KEY=\nLOG_LEVEL=\nDEFAULT_LANGUAGE=\n",
        encoding="utf-8",
    )
    from sonya.config import Settings

    s = Settings(_env_file=str(env_file))
    assert s.telegram_api_id is None
    assert s.telegram_api_hash is None
    assert s.llm_api_key is None
    assert s.log_level == "INFO"
    assert s.default_language == "en"


def test_models_metadata_has_all_tables() -> None:
    from sonya.db import models  # noqa: F401
    from sonya.db.base import Base

    expected = {
        "clients",
        "messages",
        "facts",
        "content_sets",
        "sales_attempts",
        "followups",
        "events_log",
    }
    actual = set(Base.metadata.tables.keys())
    missing = expected - actual
    assert not missing, f"Отсутствуют таблицы: {missing}"


@pytest.mark.asyncio
async def test_db_health_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Поднимаем in-memory sqlite, накатываем metadata, проверяем select 1."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    # сбросить кэши синглтонов конфига и движка
    from sonya import config as config_mod
    from sonya.db import session as session_mod

    config_mod.get_settings.cache_clear()
    session_mod.get_engine.cache_clear()
    session_mod.async_session_factory.cache_clear()

    from sonya.db import models  # noqa: F401
    from sonya.db.base import Base
    from sonya.db.session import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT 1"))).scalar_one() == 1

    await engine.dispose()

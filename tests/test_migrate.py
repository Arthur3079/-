"""Тесты для программного прогона Alembic-миграций."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Изолированная БД во временной папке + изолированный get_settings()."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")

    # Сбрасываем кэш get_settings, чтобы он перечитал env.
    from sonya import config as config_mod

    config_mod.get_settings.cache_clear()
    yield db_file
    config_mod.get_settings.cache_clear()


def _table_names(db_file: Path) -> list[str]:
    eng = create_engine(f"sqlite:///{db_file}")
    return inspect(eng).get_table_names()


def test_upgrade_to_head_creates_tables(isolated_db: Path) -> None:
    from sonya.db.migrate import upgrade_to_head

    assert not isolated_db.exists() or "clients" not in _table_names(isolated_db)

    upgrade_to_head()

    tables = set(_table_names(isolated_db))
    assert "clients" in tables
    assert "messages" in tables
    assert "facts" in tables
    assert "alembic_version" in tables


def test_upgrade_to_head_is_idempotent(isolated_db: Path) -> None:
    """Повторный вызов на актуальной БД не должен падать и не должен пересоздавать таблицы."""
    from sonya.db.migrate import upgrade_to_head

    upgrade_to_head()
    tables_first = set(_table_names(isolated_db))

    upgrade_to_head()
    tables_second = set(_table_names(isolated_db))

    assert tables_first == tables_second
    assert "clients" in tables_second


def test_upgrade_handles_missing_alembic_ini(
    isolated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Если alembic.ini не найден — функция не должна падать (только warn)."""
    from sonya.db import migrate

    monkeypatch.setattr(migrate, "_project_root", lambda: tmp_path / "nonexistent")
    migrate.upgrade_to_head()  # не должен бросить исключение

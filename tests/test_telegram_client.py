"""Юнит-тесты Telethon-обёртки (без сетевых вызовов)."""

from __future__ import annotations

import pytest

from sonya.config import Settings
from sonya.telegram import TelegramCredentialsMissing, build_client


def test_build_client_raises_without_api_id(tmp_path) -> None:
    settings = Settings(_env_file=None, telegram_phone="+10000000000")
    with pytest.raises(TelegramCredentialsMissing):
        build_client(settings, session_dir=tmp_path)


def test_build_client_raises_without_phone(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        telegram_api_id=1,
        telegram_api_hash="x",
        telegram_phone=None,
    )
    with pytest.raises(TelegramCredentialsMissing):
        build_client(settings, session_dir=tmp_path)


def test_build_client_succeeds_with_full_creds(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        telegram_api_id=1,
        telegram_api_hash="x",
        telegram_phone="+10000000000",
        telegram_session_name="test",
    )
    client = build_client(settings, session_dir=tmp_path)
    assert client is not None
    assert client.session.filename.startswith(str(tmp_path))

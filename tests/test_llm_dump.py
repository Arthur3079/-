"""Тесты для дампа промтов LLM в файл."""

from __future__ import annotations

from pathlib import Path

from sonya.llm.client import ChatMessage
from sonya.llm.dump import dump_exchange, is_debug_enabled


def test_is_debug_enabled() -> None:
    assert is_debug_enabled("DEBUG") is True
    assert is_debug_enabled("debug") is True
    assert is_debug_enabled("INFO") is False
    assert is_debug_enabled("") is False


def test_dump_exchange_writes_file(tmp_path: Path) -> None:
    messages = [
        ChatMessage(role="system", content="You are Sonya."),
        ChatMessage(role="user", content="Привет"),
        ChatMessage(role="assistant", content="hey 💕"),
    ]
    path = dump_exchange(
        log_dir=tmp_path,
        fan_id=12345,
        model="test/model:free",
        messages=messages,
        response_text="hi babe",
        prompt_tokens=42,
        completion_tokens=7,
        latency_s=1.234,
    )
    assert path is not None
    assert path.exists()
    body = path.read_text(encoding="utf-8")

    # Шапка
    assert "fan_id: `12345`" in body
    assert "model: `test/model:free`" in body
    assert "prompt_tokens: `42`" in body
    assert "completion_tokens: `7`" in body
    assert "latency_s: `1.23`" in body

    # Все сообщения попали в дамп
    assert "system" in body
    assert "user" in body
    assert "assistant" in body
    assert "You are Sonya." in body
    assert "Привет" in body

    # Reply попал
    assert "## reply" in body
    assert "hi babe" in body


def test_dump_exchange_handles_no_fan_id(tmp_path: Path) -> None:
    path = dump_exchange(
        log_dir=tmp_path,
        fan_id=None,
        model="x",
        messages=[],
        response_text="",
        prompt_tokens=None,
        completion_tokens=None,
        latency_s=0.0,
    )
    assert path is not None
    assert "unknown" in path.name
    assert "fan_id: `None`" in path.read_text(encoding="utf-8")

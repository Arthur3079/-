"""Тесты для Gemini-бэкенда (на моках; без реальных вызовов Google API)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sonya.config import Settings
from sonya.llm.backend import LLMBackend
from sonya.llm.client import ChatMessage, LLMNotConfigured
from sonya.llm.gemini import (
    GeminiBackend,
    _all_off_safety_settings,
    _split_messages,
    _to_gemini_contents,
    build_gemini_client,
)


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "telegram_api_id": 1,
        "telegram_api_hash": "x",
        "telegram_phone": "+1",
        "llm_provider": "gemini",
        "gemini_api_key": "test-gemini-key",
        "gemini_model": "gemini-test",
    }
    base.update(overrides)
    return Settings(**base)


def test_split_messages_extracts_system_and_keeps_rest_in_order() -> None:
    messages = [
        ChatMessage(role="system", content="be Sonya"),
        ChatMessage(role="user", content="hi"),
        ChatMessage(role="assistant", content="hey"),
        ChatMessage(role="user", content="how r u"),
    ]
    sys_instr, rest = _split_messages(messages)
    assert sys_instr == "be Sonya"
    assert [m.role for m in rest] == ["user", "assistant", "user"]
    assert [m.content for m in rest] == ["hi", "hey", "how r u"]


def test_split_messages_concatenates_multiple_system_messages() -> None:
    messages = [
        ChatMessage(role="system", content="part A"),
        ChatMessage(role="system", content="part B"),
        ChatMessage(role="user", content="hi"),
    ]
    sys_instr, rest = _split_messages(messages)
    assert sys_instr == "part A\n\npart B"
    assert len(rest) == 1


def test_split_messages_no_system_returns_none() -> None:
    messages = [
        ChatMessage(role="user", content="hi"),
        ChatMessage(role="assistant", content="hey"),
    ]
    sys_instr, rest = _split_messages(messages)
    assert sys_instr is None
    assert len(rest) == 2


def test_to_gemini_contents_maps_assistant_to_model_role() -> None:
    messages = [
        ChatMessage(role="user", content="hi"),
        ChatMessage(role="assistant", content="hey"),
    ]
    contents = _to_gemini_contents(messages)
    # Первый — user, второй — model (Gemini-специфичная роль для assistant).
    assert contents[0].role == "user"
    assert contents[1].role == "model"


def test_all_off_safety_settings_covers_critical_categories_with_off() -> None:
    from google.genai import types

    settings_list = _all_off_safety_settings()
    categories = {s.category for s in settings_list}
    assert types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT in categories
    assert types.HarmCategory.HARM_CATEGORY_HARASSMENT in categories
    # Все треды должны быть OFF (не BLOCK_NONE — OFF полностью отключает фильтр).
    for s in settings_list:
        assert s.threshold == types.HarmBlockThreshold.OFF


def test_build_gemini_client_raises_without_key() -> None:
    s = _settings(gemini_api_key=None)
    with pytest.raises(LLMNotConfigured) as exc:
        build_gemini_client(s)
    assert "GEMINI_API_KEY" in str(exc.value)


def test_gemini_backend_satisfies_protocol() -> None:
    """GeminiBackend должен соответствовать LLMBackend Protocol."""
    backend = GeminiBackend(SimpleNamespace(), _settings())  # type: ignore[arg-type]
    assert isinstance(backend, LLMBackend)
    assert backend.model == "gemini-test"
    assert "generativelanguage" in backend.endpoint


@pytest.mark.asyncio
async def test_gemini_backend_generate_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Замокаем generate_content и убедимся что generate() извлекает .text."""
    captured: dict[str, Any] = {}

    def fake_generate(*, model: str, contents: Any, config: Any) -> Any:
        captured["model"] = model
        captured["contents"] = contents
        captured["config"] = config
        return SimpleNamespace(
            text="hey babe 💕",
            usage_metadata=SimpleNamespace(prompt_token_count=42, candidates_token_count=7),
            candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))],
        )

    fake_client = SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate))
    backend = GeminiBackend(fake_client, _settings())  # type: ignore[arg-type]

    messages = [
        ChatMessage(role="system", content="be Sonya"),
        ChatMessage(role="user", content="hi"),
    ]
    out = await backend.generate(messages, fan_id=42)
    assert out == "hey babe 💕"
    assert captured["model"] == "gemini-test"
    # System message должен уйти в config.system_instruction, не в contents.
    assert len(captured["contents"]) == 1
    assert captured["contents"][0].role == "user"
    assert captured["config"].system_instruction == "be Sonya"


@pytest.mark.asyncio
async def test_gemini_backend_generate_handles_blocked_response() -> None:
    """Если Gemini вернул пустой ответ (NSFW filter) — generate() возвращает '' (хендлер потом fallback)."""
    fake_resp = SimpleNamespace(
        text="",
        usage_metadata=None,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="SAFETY"))],
        prompt_feedback=SimpleNamespace(block_reason=SimpleNamespace(name="SAFETY")),
    )

    def fake_generate(**kwargs: Any) -> Any:
        return fake_resp

    fake_client = SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate))
    backend = GeminiBackend(fake_client, _settings())  # type: ignore[arg-type]

    out = await backend.generate(
        [ChatMessage(role="user", content="anything")],
        fan_id=1,
    )
    assert out == ""

"""Тесты LLM-слоя: клиент-фабрика, рендер карточки, оркестратор."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.config import Settings
from sonya.db.base import Base
from sonya.db.models import Client, FanStatus, Message, MessageDirection, MessageMediaType
from sonya.llm.client import (
    ChatMessage,
    LLMNotConfigured,
    build_llm_client,
    complete_chat,
)
from sonya.llm.conversation import (
    fetch_history,
    generate_reply,
    history_to_chat_messages,
)
from sonya.llm.prompts import (
    CLIENT_CARD_SEPARATOR,
    SYSTEM_PROMPT_BASE,
    build_system_prompt,
    render_client_card,
)


def _settings(**overrides: Any) -> Settings:
    return Settings(
        llm_api_key="sk-test",
        llm_model="test/model:free",
        llm_max_tokens=100,
        llm_temperature=0.5,
        llm_history_limit=5,
        **overrides,
    )


def test_build_llm_client_raises_without_key() -> None:
    s = Settings()
    with pytest.raises(LLMNotConfigured):
        build_llm_client(s)


def test_build_llm_client_returns_client_with_correct_base_url() -> None:
    s = _settings()
    client = build_llm_client(s)
    assert str(client.base_url).rstrip("/") == "https://openrouter.ai/api/v1"


def test_build_llm_client_falls_back_to_legacy_openrouter_key() -> None:
    """Старые .env с OPENROUTER_API_KEY должны продолжать работать."""
    s = Settings(openrouter_api_key="sk-or-v1-legacy")
    assert s.effective_llm_api_key == "sk-or-v1-legacy"
    client = build_llm_client(s)
    assert client.api_key == "sk-or-v1-legacy"


def test_llm_api_key_takes_precedence_over_legacy() -> None:
    s = Settings(llm_api_key="sk-new", openrouter_api_key="sk-or-v1-legacy")
    assert s.effective_llm_api_key == "sk-new"


def test_build_llm_client_respects_custom_base_url() -> None:
    """LLM_BASE_URL позволяет переключаться на NVIDIA NIM, Groq и т.д."""
    s = _settings(llm_base_url="https://integrate.api.nvidia.com/v1")
    client = build_llm_client(s)
    assert str(client.base_url).rstrip("/") == "https://integrate.api.nvidia.com/v1"


def test_render_client_card_empty() -> None:
    c = Client(fan_id=1, status=FanStatus.ACTIVE)
    assert render_client_card(c) == ""


def test_render_client_card_packs_known_fields() -> None:
    c = Client(
        fan_id=1,
        username="bob",
        first_name="Bob",
        display_name="Bob",
        status=FanStatus.ACTIVE,
        language="en",
        country_guess="US",
        fan_type="A2",
        type_confidence="mid",
        notes="prefers mornings",
    )
    card = render_client_card(c)
    assert "Bob" in card
    assert "en" in card
    assert "US" in card
    assert "A2" in card
    assert "mid" in card
    assert "mornings" in card


def test_build_system_prompt_without_card_is_base() -> None:
    assert build_system_prompt() == SYSTEM_PROMPT_BASE


def test_build_system_prompt_with_card_appends() -> None:
    card = "Name they go by: Bob"
    out = build_system_prompt(client_card=card)
    assert SYSTEM_PROMPT_BASE in out
    assert "Bob" in out
    assert "[Notes about this specific fan]" in out
    # Сумма частей должна сходиться с длиной финального промта.
    assert len(out) == len(SYSTEM_PROMPT_BASE) + len(CLIENT_CARD_SEPARATOR) + len(card)


def test_build_system_prompt_with_persona_and_few_shot() -> None:
    persona = "[STYLE] active grain: G7 friendly-clear."
    few_shot = "[FEW_SHOT good]\n  ✓ привет) как день?)"
    out = build_system_prompt(persona_block=persona, few_shot_block=few_shot)
    assert "[Voice & rails for THIS turn]" in out
    assert "G7" in out
    assert "[Few-shot examples" in out
    # Persona block must precede few-shot.
    assert out.index("[Voice & rails") < out.index("[Few-shot examples")


def test_history_to_chat_messages_maps_directions_and_skips_empty() -> None:
    msgs = [
        Message(
            fan_id=1,
            direction=MessageDirection.INCOMING,
            media_type=MessageMediaType.TEXT,
            content="hi",
            timestamp=datetime.now(timezone.utc),
        ),
        Message(
            fan_id=1,
            direction=MessageDirection.OUTGOING,
            media_type=MessageMediaType.TEXT,
            content="hey",
            timestamp=datetime.now(timezone.utc),
        ),
        Message(
            fan_id=1,
            direction=MessageDirection.OUTGOING,
            media_type=MessageMediaType.PHOTO,
            content=None,
            timestamp=datetime.now(timezone.utc),
        ),
    ]
    out = history_to_chat_messages(msgs)
    assert [m.role for m in out] == ["user", "assistant"]
    assert [m.content for m in out] == ["hi", "hey"]


@pytest.mark.asyncio
async def test_fetch_history_returns_chronological_order() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    base_ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    async with factory() as s, s.begin():
        s.add(Client(fan_id=42, status=FanStatus.ACTIVE))
        for i, txt in enumerate(["one", "two", "three", "four"]):
            s.add(
                Message(
                    fan_id=42,
                    direction=MessageDirection.INCOMING,
                    media_type=MessageMediaType.TEXT,
                    content=txt,
                    timestamp=base_ts.replace(minute=i),
                )
            )

    async with factory() as s:
        rows = await fetch_history(s, fan_id=42, limit=3)

    assert [m.content for m in rows] == ["two", "three", "four"]


@pytest.mark.asyncio
async def test_complete_chat_returns_text_from_canned_response() -> None:
    canned = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="  hello there  "))]
    )

    class _Stub:
        class chat:
            class completions:
                @staticmethod
                async def create(**_kw: Any) -> Any:
                    return canned

    s = _settings()
    out = await complete_chat(_Stub(), settings=s, messages=[ChatMessage("user", "hi")])  # type: ignore[arg-type]
    assert out == "hello there"


@pytest.mark.asyncio
async def test_generate_reply_passes_system_and_history_to_llm() -> None:
    """generate_reply должен сконструировать system + историю и передать в complete_chat."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    captured: dict[str, Any] = {}

    canned = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="hey babe"))])

    class _Stub:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs: Any) -> Any:
                    captured.update(kwargs)
                    return canned

    base_ts = datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)
    async with factory() as s, s.begin():
        s.add(Client(fan_id=7, first_name="Bob", display_name="Bob", status=FanStatus.ACTIVE))
        for i, (direction, txt) in enumerate(
            [
                (MessageDirection.INCOMING, "hi"),
                (MessageDirection.OUTGOING, "heyy"),
                (MessageDirection.INCOMING, "what r u up to"),
            ]
        ):
            s.add(
                Message(
                    fan_id=7,
                    direction=direction,
                    media_type=MessageMediaType.TEXT,
                    content=txt,
                    timestamp=base_ts.replace(minute=i),
                )
            )

    async with factory() as s:
        from sqlalchemy import select

        client = (await s.execute(select(Client).where(Client.fan_id == 7))).scalar_one()
        from sonya.llm.openai_backend import OpenAICompatBackend

        backend = OpenAICompatBackend(_Stub(), _settings())  # type: ignore[arg-type]
        out = await generate_reply(
            backend=backend,
            settings=_settings(),
            session=s,
            client=client,
        )

    assert out == "hey babe"
    msgs = captured["messages"]
    assert msgs[0]["role"] == "system"
    assert "Sonya" in msgs[0]["content"]
    assert "Bob" in msgs[0]["content"]
    assert msgs[1:] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "heyy"},
        {"role": "user", "content": "what r u up to"},
    ]
    assert captured["model"] == "test/model:free"
    assert captured["max_tokens"] == 100
    assert captured["temperature"] == 0.5

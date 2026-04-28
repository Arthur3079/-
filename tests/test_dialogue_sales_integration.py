"""End-to-end test: DialogueService offers a content set on a CONTENT_REQUEST.

Uses the real ContentSet/SalesAttempt schema and a stub LLM backend, so we
verify the wiring between dialogue → recommend → sales engine without
needing a real LLM or Telegram client.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.config import Settings
from sonya.crm.repository import get_or_create_client, save_message
from sonya.db import models  # noqa: F401
from sonya.db.base import Base
from sonya.db.models import Client, ContentSet, MessageDirection, SalesAttempt
from sonya.dialogue.service import DialogueService
from sonya.llm.client import ChatMessage


class _StubBackend:
    """Tiny LLM backend that returns a canned reply, ignoring inputs."""

    model = "stub-1"
    endpoint = "stub://"

    def __init__(self, reply: str = "sure — what catches your eye?") -> None:
        self._reply = reply

    async def generate(self, messages: list[ChatMessage], *, fan_id: int) -> str:
        return self._reply

    async def aclose(self) -> None:  # pragma: no cover
        pass


@pytest.fixture
async def session_and_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        await get_or_create_client(s, fan_id=10, username="bob", first_name="Bob", last_name=None)
        # Seed enough inbound history to clear the CadenceEngine
        # `MIN_INBOUND_BEFORE_OFFER` gate (no PPV in first 5 turns).
        for i in range(6):
            await save_message(
                s,
                fan_id=10,
                tg_message_id=1000 + i,
                direction=MessageDirection.INCOMING,
                content=f"warmup {i}",
            )
        s.add(
            ContentSet(
                code="07",
                name="Beach_set",
                price_stars=300,
                price_usd_equivalent=10.0,
                description=None,
                target_types="A1,A5",
                is_active=True,
            )
        )
        await s.commit()
        client = (await s.execute(select(Client).where(Client.fan_id == 10))).scalar_one()
        yield s, client
    await engine.dispose()


async def test_content_request_appends_cta_bubble(session_and_client) -> None:
    session, client = session_and_client
    settings = Settings(_env_file=None)
    service = DialogueService(settings=settings, backend=_StubBackend())

    result = await service.handle_incoming(session, client=client, text="send me a pic")

    assert result.reply_text  # didn't get safety-blocked
    assert result.intent == "content_request"
    assert result.offered_set_code == "07"
    assert result.invoice_payload and result.invoice_payload.startswith("sonya:10:")
    # Last bubble is the CTA pointing at the payment bot.
    assert result.bubbles
    assert "/buy" in result.bubbles[-1].lower() or "@" in result.bubbles[-1]


async def test_greeting_does_not_offer(session_and_client) -> None:
    session, client = session_and_client
    settings = Settings(_env_file=None)
    service = DialogueService(settings=settings, backend=_StubBackend("hi 💕"))

    result = await service.handle_incoming(session, client=client, text="hi")

    assert result.reply_text
    assert result.intent == "greeting"
    assert result.offered_set_code is None
    assert result.invoice_payload is None


async def test_no_offer_in_first_message(session_and_client) -> None:
    """A brand-new fan asking for content on turn 1 must NOT get an offer."""
    session, _seeded_client = session_and_client
    settings = Settings(_env_file=None)
    service = DialogueService(settings=settings, backend=_StubBackend())

    # Fresh fan with zero history.
    from sonya.crm.repository import get_or_create_client

    fresh = await get_or_create_client(
        session, fan_id=42, username="new", first_name="N", last_name=None
    )
    result = await service.handle_incoming(session, client=fresh, text="send me a pic")
    assert result.intent == "content_request"
    # CadenceEngine.MIN_INBOUND_BEFORE_OFFER blocks the recommendation.
    assert result.offered_set_code is None
    assert result.invoice_payload is None


async def test_paused_offer_still_persists_attempt(session_and_client) -> None:
    """The offer attempt is logged regardless of pause (pause skip is in handler)."""
    session, client = session_and_client
    settings = Settings(_env_file=None)
    service = DialogueService(settings=settings, backend=_StubBackend())

    await service.handle_incoming(session, client=client, text="how much is the set?")
    await session.commit()

    rows = (await session.execute(select(SalesAttempt))).scalars().all()
    assert len(rows) == 1


class _RecordingBackend:
    """Stub backend that records the system prompt of the last LLM call."""

    model = "stub-1"
    endpoint = "stub://"

    def __init__(self) -> None:
        self.captured_system: str | None = None

    async def generate(self, messages: list[ChatMessage], *, fan_id: int) -> str:
        for m in messages:
            if m.role == "system":
                self.captured_system = m.content
                break
        return "hey) just woke up)"

    async def aclose(self) -> None:  # pragma: no cover
        pass


async def test_system_prompt_includes_persona_and_few_shot(session_and_client) -> None:
    """Phase 2: dialogue service injects grain + few-shot blocks into the system
    prompt for every LLM call."""
    session, client = session_and_client
    settings = Settings(_env_file=None)
    backend = _RecordingBackend()
    service = DialogueService(settings=settings, backend=backend)

    await service.handle_incoming(session, client=client, text="hi how are you")

    assert backend.captured_system is not None
    sysp = backend.captured_system
    # Persona-block markers come from sonya.library.selectors.render_persona_block.
    assert "[Voice & rails for THIS turn]" in sysp
    assert "[STYLE]" in sysp
    # Few-shot block must appear after persona when both are present.
    if "[Few-shot examples" in sysp:
        assert sysp.index("[Voice & rails") < sysp.index("[Few-shot examples")

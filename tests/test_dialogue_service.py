"""Tests for sonya.dialogue.service.DialogueService.

Uses an in-memory sqlite session, a fake LLMBackend, and (optionally) a tiny
KnowledgeIndex. No Telethon involvement.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.config import Settings
from sonya.crm.facts import upsert_fact
from sonya.crm.repository import get_or_create_client, save_message
from sonya.db import models  # noqa: F401
from sonya.db.base import Base
from sonya.db.models import Client, MessageDirection
from sonya.dialogue import DialogueService, SkipReason
from sonya.knowledge.loader import KnowledgeChunk
from sonya.knowledge.retrieval import KnowledgeIndex
from sonya.llm.client import ChatMessage


class FakeBackend:
    """Minimal LLMBackend impl for DialogueService tests."""

    def __init__(self, response: str = "hey love 💛", *, fail: bool = False) -> None:
        self.response = response
        self.fail = fail
        self.calls: list[list[ChatMessage]] = []

    @property
    def model(self) -> str:
        return "fake/model"

    @property
    def endpoint(self) -> str:
        return "fake://"

    async def generate(self, messages: Iterable[ChatMessage], *, fan_id: int) -> str:
        msgs = list(messages)
        self.calls.append(msgs)
        if self.fail:
            raise RuntimeError("simulated LLM failure")
        return self.response

    async def aclose(self) -> None:
        pass


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _settings() -> Settings:
    return Settings(_env_file=None, llm_history_limit=5)


async def _seed_client(session, fan_id: int = 1) -> Client:
    c = await get_or_create_client(
        session, fan_id=fan_id, username="x", first_name="X", last_name=None
    )
    await session.commit()
    return c


async def test_happy_path_returns_llm_reply(session) -> None:
    client = await _seed_client(session)
    backend = FakeBackend("hey love")
    svc = DialogueService(settings=_settings(), backend=backend)
    res = await svc.handle_incoming(session, client=client, text="hi")
    assert res.should_send
    assert res.reply_text == "hey love"
    assert res.skipped_reason is SkipReason.NONE
    assert backend.calls, "LLM must have been invoked"


async def test_safety_pre_blocks_minor(session) -> None:
    client = await _seed_client(session)
    backend = FakeBackend()
    svc = DialogueService(settings=_settings(), backend=backend)
    res = await svc.handle_incoming(session, client=client, text="hi i'm 15")
    assert res.skipped_reason is SkipReason.SAFETY_PRE_BLOCK
    assert res.handoff_required is True
    assert res.reply_text  # safe canned reply
    assert not backend.calls, "LLM must NOT be called when pre-block fires"


async def test_safety_pre_blocks_offplatform(session) -> None:
    client = await _seed_client(session)
    backend = FakeBackend()
    svc = DialogueService(settings=_settings(), backend=backend)
    res = await svc.handle_incoming(session, client=client, text="send me your cashapp")
    assert res.skipped_reason is SkipReason.SAFETY_PRE_BLOCK
    assert not backend.calls


async def test_safety_pre_drops_silently_on_stop_request(session) -> None:
    client = await _seed_client(session)
    backend = FakeBackend()
    svc = DialogueService(settings=_settings(), backend=backend)
    res = await svc.handle_incoming(session, client=client, text="leave me alone")
    assert res.skipped_reason is SkipReason.SAFETY_PRE_BLOCK
    assert res.reply_text is None  # silent drop, no canned reply
    assert not backend.calls
    # Suppression persisted on the client.
    await session.refresh(client)
    assert client.suppression_until is not None
    assert "stop_request" in (client.flags or "")


async def test_safety_post_blocks_unsafe_llm_output(session) -> None:
    client = await _seed_client(session)
    backend = FakeBackend("text me at +1 415 555 0123 anytime")
    svc = DialogueService(settings=_settings(), backend=backend)
    res = await svc.handle_incoming(session, client=client, text="hi")
    assert res.skipped_reason is SkipReason.SAFETY_POST_BLOCK
    assert "+1 415" not in (res.reply_text or "")


async def test_llm_failure_triggers_fallback(session) -> None:
    client = await _seed_client(session)
    backend = FakeBackend(fail=True)
    svc = DialogueService(settings=_settings(), backend=backend)
    res = await svc.handle_incoming(session, client=client, text="hi")
    assert res.skipped_reason is SkipReason.LLM_FAILED
    assert res.reply_text and "sec" in res.reply_text.lower()


async def test_no_backend_returns_stub(session) -> None:
    client = await _seed_client(session)
    svc = DialogueService(settings=_settings(), backend=None)
    res = await svc.handle_incoming(session, client=client, text="hi there")
    assert res.skipped_reason is SkipReason.LLM_NOT_CONFIGURED
    assert res.reply_text and "[stub]" in res.reply_text


async def test_empty_incoming_skipped(session) -> None:
    client = await _seed_client(session)
    backend = FakeBackend()
    svc = DialogueService(settings=_settings(), backend=backend)
    res = await svc.handle_incoming(session, client=client, text="   ")
    assert res.skipped_reason is SkipReason.EMPTY_INCOMING
    assert res.reply_text is None
    assert not backend.calls


async def test_facts_appear_in_system_prompt(session) -> None:
    client = await _seed_client(session)
    await upsert_fact(session, fan_id=client.fan_id, key="city", value="NYC")
    await session.commit()
    backend = FakeBackend("ok")
    svc = DialogueService(settings=_settings(), backend=backend)
    await svc.handle_incoming(session, client=client, text="how are you?")
    assert backend.calls
    sys_msg = backend.calls[0][0]
    assert sys_msg.role == "system"
    assert "city: NYC" in sys_msg.content


async def test_knowledge_snippets_appear_in_system_prompt(session) -> None:
    client = await _seed_client(session)
    chunks = [
        KnowledgeChunk(
            file_id="welcome_flow",
            section="Welcome Flow",
            text="Greet new fans warmly with one short message.",
            tags=frozenset({"welcome", "playbook"}),
            char_count=50,
        )
    ]
    backend = FakeBackend("hi sweetie")
    svc = DialogueService(settings=_settings(), backend=backend, knowledge=KnowledgeIndex(chunks))
    await svc.handle_incoming(session, client=client, text="welcome new fan playbook")
    sys_msg = backend.calls[0][0]
    assert "Greet new fans warmly" in sys_msg.content


async def test_history_passed_to_llm(session) -> None:
    client = await _seed_client(session)
    await save_message(
        session,
        fan_id=client.fan_id,
        tg_message_id=1,
        direction=MessageDirection.INCOMING,
        content="earlier message",
    )
    await session.commit()
    backend = FakeBackend("ok")
    svc = DialogueService(settings=_settings(), backend=backend)
    await svc.handle_incoming(session, client=client, text="hi")
    assert backend.calls
    msgs = backend.calls[0]
    contents = [m.content for m in msgs]
    assert any("earlier message" in c for c in contents)


async def test_intent_and_fan_type_populated(session) -> None:
    """Phase 4: result carries intent + fan_type."""
    client = await _seed_client(session)
    backend = FakeBackend("hey love")
    svc = DialogueService(settings=_settings(), backend=backend)
    res = await svc.handle_incoming(session, client=client, text="hi")
    assert res.intent == "greeting"
    assert res.fan_type == "newcomer"


async def test_orchestrator_hints_in_system_prompt(session) -> None:
    """Phase 4: intent + fan_type are surfaced to the LLM."""
    client = await _seed_client(session)
    backend = FakeBackend("ok")
    svc = DialogueService(settings=_settings(), backend=backend)
    await svc.handle_incoming(session, client=client, text="how much?")
    sys_msg = backend.calls[0][0]
    assert "current_message_intent: price_question" in sys_msg.content
    assert "fan_type: newcomer" in sys_msg.content


async def test_bubbles_populated_for_long_reply(session) -> None:
    client = await _seed_client(session)
    long_reply = (
        "First substantial paragraph that's long enough to count as one bubble "
        "and keeps going with more words to comfortably cross the threshold.\n\n"
        "Second substantial paragraph that's also long enough to be its own "
        "bubble and contains more filler text to push us over the limit too."
    )
    backend = FakeBackend(long_reply)
    svc = DialogueService(settings=_settings(), backend=backend)
    res = await svc.handle_incoming(session, client=client, text="tell me about you")
    assert len(res.bubbles) >= 2
    assert res.send_bubbles == res.bubbles


async def test_short_reply_one_bubble(session) -> None:
    client = await _seed_client(session)
    backend = FakeBackend("hey 💛")
    svc = DialogueService(settings=_settings(), backend=backend)
    res = await svc.handle_incoming(session, client=client, text="hi")
    assert res.bubbles == ("hey 💛",)


async def test_used_knowledge_populated(session) -> None:
    client = await _seed_client(session)
    chunks = [
        KnowledgeChunk(
            file_id="welcome_flow",
            section="Welcome Flow",
            text="Greet new fans warmly with one short message.",
            tags=frozenset({"welcome", "playbook", "newcomer"}),
            char_count=50,
        )
    ]
    backend = FakeBackend("hi sweetie")
    svc = DialogueService(settings=_settings(), backend=backend, knowledge=KnowledgeIndex(chunks))
    res = await svc.handle_incoming(session, client=client, text="welcome new fan playbook")
    assert "welcome_flow" in res.used_knowledge

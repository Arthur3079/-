"""Unit tests for the admin command dispatcher (Phase 8)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.admin.commands import dispatch_command
from sonya.admin.repository import (
    list_recent_actions,
    pause_client,
    resume_client,
    update_notes,
)
from sonya.config import Settings
from sonya.crm.facts import upsert_fact
from sonya.crm.repository import get_or_create_client
from sonya.db import models  # noqa: F401
from sonya.db.base import Base
from sonya.db.models import AdminAction, Client


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        await get_or_create_client(
            s, fan_id=42, username="alice", first_name="Alice", last_name=None
        )
        await get_or_create_client(s, fan_id=99, username="bob", first_name="Bob", last_name=None)
        await s.commit()
        yield s
    await engine.dispose()


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, admin_user_ids=[1])


async def test_help(session, settings) -> None:
    res = await dispatch_command(session, admin_user_id=1, raw_text="/help", settings=settings)
    assert res.ok
    assert "/pause" in res.text
    assert "/card" in res.text


async def test_status_zero_state(session, settings) -> None:
    res = await dispatch_command(session, admin_user_id=1, raw_text="/status", settings=settings)
    assert res.ok
    assert "clients: 2 total" in res.text
    assert "0 paused" in res.text


async def test_pause_marks_client_and_logs(session, settings) -> None:
    res = await dispatch_command(
        session,
        admin_user_id=1,
        raw_text="/pause 42 too creepy",
        settings=settings,
    )
    assert res.ok, res.text
    await session.commit()

    fan = (await session.execute(select(Client).where(Client.fan_id == 42))).scalar_one()
    assert fan.is_paused is True
    assert fan.paused_reason == "too creepy"

    actions = await list_recent_actions(session)
    assert len(actions) == 1
    assert actions[0].action_type == "pause"
    assert actions[0].target_fan_id == 42


async def test_pause_then_resume(session, settings) -> None:
    await dispatch_command(session, admin_user_id=1, raw_text="/pause 42", settings=settings)
    await dispatch_command(session, admin_user_id=1, raw_text="/resume 42", settings=settings)
    await session.commit()
    fan = (await session.execute(select(Client).where(Client.fan_id == 42))).scalar_one()
    assert fan.is_paused is False
    assert fan.paused_reason is None
    actions = await list_recent_actions(session)
    types = {a.action_type for a in actions}
    assert {"pause", "resume"} <= types


async def test_handoff_prefixes_reason(session, settings) -> None:
    res = await dispatch_command(
        session,
        admin_user_id=1,
        raw_text="/handoff 42 vip case",
        settings=settings,
    )
    assert res.ok
    await session.commit()
    fan = (await session.execute(select(Client).where(Client.fan_id == 42))).scalar_one()
    assert fan.is_paused is True
    assert fan.paused_reason and fan.paused_reason.startswith("handoff:")


async def test_card_renders_known_facts(session, settings) -> None:
    await upsert_fact(session, fan_id=42, key="city", value="Lisbon", confidence="high")
    await session.commit()
    res = await dispatch_command(session, admin_user_id=1, raw_text="/card 42", settings=settings)
    assert res.ok
    assert "fan_id: 42" in res.text
    assert "Alice" in res.text
    assert "city: Lisbon" in res.text


async def test_facts_command(session, settings) -> None:
    await upsert_fact(session, fan_id=42, key="job", value="DJ")
    await session.commit()
    res = await dispatch_command(session, admin_user_id=1, raw_text="/facts 42", settings=settings)
    assert res.ok
    assert "job: DJ" in res.text


async def test_note_appends_and_audits(session, settings) -> None:
    res = await dispatch_command(
        session,
        admin_user_id=1,
        raw_text="/note 42 reminded that he likes punk",
        settings=settings,
    )
    assert res.ok
    await session.commit()
    fan = (await session.execute(select(Client).where(Client.fan_id == 42))).scalar_one()
    assert fan.notes is not None
    assert "punk" in fan.notes


async def test_note_requires_text(session, settings) -> None:
    res = await dispatch_command(session, admin_user_id=1, raw_text="/note 42", settings=settings)
    assert not res.ok
    assert "usage" in res.text.lower()


async def test_unknown_command(session, settings) -> None:
    res = await dispatch_command(session, admin_user_id=1, raw_text="/blarg 42", settings=settings)
    assert not res.ok
    assert "unknown" in res.text.lower()


async def test_non_command_input(session, settings) -> None:
    res = await dispatch_command(
        session, admin_user_id=1, raw_text="hello sonya", settings=settings
    )
    assert not res.ok


async def test_card_for_missing_fan(session, settings) -> None:
    res = await dispatch_command(session, admin_user_id=1, raw_text="/card 7777", settings=settings)
    assert not res.ok
    assert "not found" in res.text


async def test_dump_prompt_runs_without_llm(session, settings) -> None:
    res = await dispatch_command(
        session, admin_user_id=1, raw_text="/dump_prompt 42", settings=settings
    )
    assert res.ok
    assert "fan_id=42" in res.text


async def test_repository_pause_unknown_fan_returns_none(session) -> None:
    out = await pause_client(session, fan_id=12345)
    assert out is None


async def test_repository_resume_unknown_fan_returns_none(session) -> None:
    out = await resume_client(session, fan_id=12345)
    assert out is None


async def test_repository_update_notes_unknown_fan(session) -> None:
    out = await update_notes(session, fan_id=12345, note="x")
    assert out is None


async def test_admin_actions_recorded_correctly(session, settings) -> None:
    for cmd in ("/pause 42", "/resume 42", "/note 42 hi"):
        await dispatch_command(session, admin_user_id=1, raw_text=cmd, settings=settings)
    await session.commit()
    rows = (await session.execute(select(AdminAction))).scalars().all()
    assert len(rows) == 3
    assert all(r.admin_user_id == 1 for r in rows)
    assert all(r.target_fan_id == 42 for r in rows)

"""Unit tests for sonya.crm.facts (in-memory sqlite)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.crm.facts import (
    delete_fact,
    facts_dict,
    list_facts,
    upsert_fact,
)
from sonya.crm.repository import get_or_create_client
from sonya.db import models  # noqa: F401  (registers models on metadata)
from sonya.db.base import Base


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        # The facts UNIQUE constraint requires a parent client row.
        await get_or_create_client(
            s, fan_id=1, username="testfan", first_name="Test", last_name=None
        )
        await s.commit()
        yield s
    await engine.dispose()


async def test_upsert_creates_new_fact(session) -> None:
    fact = await upsert_fact(session, fan_id=1, key="city", value="NYC")
    assert fact.id is not None
    assert fact.key == "city"
    assert fact.value == "NYC"
    assert fact.confidence == "mid"


async def test_upsert_is_idempotent_on_same_value(session) -> None:
    f1 = await upsert_fact(session, fan_id=1, key="pet", value="cat")
    f2 = await upsert_fact(session, fan_id=1, key="pet", value="cat")
    assert f1.id == f2.id  # same row reused


async def test_upsert_updates_existing(session) -> None:
    await upsert_fact(session, fan_id=1, key="city", value="NYC", confidence="low")
    f2 = await upsert_fact(session, fan_id=1, key="city", value="Brooklyn", confidence="high")
    assert f2.value == "Brooklyn"
    assert f2.confidence == "high"


async def test_list_facts_returns_views(session) -> None:
    await upsert_fact(session, fan_id=1, key="city", value="NYC")
    await upsert_fact(session, fan_id=1, key="job", value="dev")
    rows = await list_facts(session, fan_id=1)
    assert {r.key for r in rows} == {"city", "job"}
    assert all(r.confidence in ("low", "mid", "high") for r in rows)


async def test_facts_dict_one_per_key(session) -> None:
    await upsert_fact(session, fan_id=1, key="city", value="NYC")
    await upsert_fact(session, fan_id=1, key="city", value="Brooklyn")
    d = await facts_dict(session, fan_id=1)
    assert d == {"city": "Brooklyn"}


async def test_delete_fact(session) -> None:
    await upsert_fact(session, fan_id=1, key="pet", value="cat")
    assert await delete_fact(session, fan_id=1, key="pet") is True
    assert await delete_fact(session, fan_id=1, key="pet") is False
    assert await facts_dict(session, fan_id=1) == {}


async def test_invalid_confidence_rejected(session) -> None:
    with pytest.raises(ValueError):
        await upsert_fact(session, fan_id=1, key="x", value="y", confidence="bogus")


async def test_empty_value_rejected(session) -> None:
    with pytest.raises(ValueError):
        await upsert_fact(session, fan_id=1, key="city", value="")
    with pytest.raises(ValueError):
        await upsert_fact(session, fan_id=1, key="", value="NYC")

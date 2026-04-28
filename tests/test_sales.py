"""Tests for Phase 6: catalog import, recommend, sales engine."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonya.config import Settings
from sonya.crm.repository import get_or_create_client
from sonya.db import models  # noqa: F401
from sonya.db.base import Base
from sonya.db.models import ContentDelivery, ContentSet, SaleOutcome, SalesAttempt
from sonya.dialogue.intent import Intent
from sonya.sales.catalog_importer import (
    import_catalog_file,
    parse_catalog,
    upsert_entry,
)
from sonya.sales.engine import build_recommendation, register_invoice_request
from sonya.sales.recommend import recommend_for_fan

CATALOG_SAMPLE = """# Каталог

---

## 01. Disco_ball_white_panties_studio
**Кадров:** ~12 | **Цвет:** бирюзовый

- **Vibe:** студия-гламур, disco ball.
- **Tier:** Tier 2 mid PPV — **$22-28**.
- **Грань Сони:** G3 + G6.
- **Подходит типам:** C2 playful flirt, C4 status spender, B1 whale.
- **Не предлагать:** C7 vulnerable, C1 shy.
- **PPV-копи:** ...

---

## 02. Cheap_starter
**Кадров:** ~8 | **Цвет:** оранжевый

- **Vibe:** lite.
- **Tier:** Tier 1 — **$10**.
- **Подходит типам:** A1 newcomer.
- **PPV-копи:** ...
"""


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        await get_or_create_client(s, fan_id=1, username="x", first_name="X", last_name=None)
        await s.commit()
        yield s
    await engine.dispose()


def test_parse_catalog_extracts_two_entries() -> None:
    entries = parse_catalog(CATALOG_SAMPLE)
    assert len(entries) == 2
    e1 = entries[0]
    assert e1.code == "01"
    assert "Disco_ball" in e1.name
    assert e1.price_usd_low == 22
    assert e1.price_usd_high == 28
    assert e1.theme == "бирюзовый"
    assert "C2" in e1.target_types
    assert "B1" in e1.target_types
    assert "C7" in e1.blocked_types


def test_parse_catalog_handles_single_price() -> None:
    entries = parse_catalog(CATALOG_SAMPLE)
    e2 = entries[1]
    assert e2.code == "02"
    assert e2.price_usd_low == 10
    assert e2.price_usd_high is None
    assert e2.price_usd_equivalent == 10.0


def test_parse_catalog_returns_empty_for_no_headings() -> None:
    assert parse_catalog("just text\n# wrong heading level") == []


async def test_upsert_entry_is_idempotent(session) -> None:
    entries = parse_catalog(CATALOG_SAMPLE)
    for e in entries:
        await upsert_entry(session, entry=e)
    await upsert_entry(session, entry=entries[0])  # second time
    await session.commit()

    rows = (await session.execute(select(ContentSet))).scalars().all()
    assert len(rows) == 2
    codes = {r.code for r in rows}
    assert codes == {"01", "02"}


async def test_import_catalog_file_uses_real_file(tmp_path: Path, session) -> None:
    p = tmp_path / "catalog.md"
    p.write_text(CATALOG_SAMPLE, encoding="utf-8")
    n = await import_catalog_file(session, path=p)
    assert n == 2
    await session.commit()
    rows = (await session.execute(select(ContentSet))).scalars().all()
    assert len(rows) == 2


async def test_import_catalog_missing_file_returns_zero(tmp_path: Path, session) -> None:
    n = await import_catalog_file(session, path=tmp_path / "no.md")
    assert n == 0


async def test_recommend_returns_empty_when_no_catalog(session) -> None:
    out = await recommend_for_fan(session, fan_id=1, fan_type_lite="REGULAR")
    assert out == []


async def test_recommend_picks_target_match(session) -> None:
    for e in parse_catalog(CATALOG_SAMPLE):
        await upsert_entry(session, entry=e)
    await session.commit()

    out = await recommend_for_fan(session, fan_id=1, fan_type_lite="WHALE")
    assert out
    # First should be the disco set (B1 in target_types).
    assert out[0].code == "01"


async def test_recommend_skips_already_delivered(session) -> None:
    for e in parse_catalog(CATALOG_SAMPLE):
        await upsert_entry(session, entry=e)
    await session.commit()
    cs = (await session.execute(select(ContentSet).where(ContentSet.code == "01"))).scalar_one()
    session.add(
        ContentDelivery(
            fan_id=1,
            content_set_id=cs.id,
            delivered_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            delivery_status="delivered",
        )
    )
    await session.commit()
    out = await recommend_for_fan(session, fan_id=1, fan_type_lite="WHALE")
    codes = [c.code for c in out]
    assert "01" not in codes


async def test_recommend_risky_fan_gets_nothing(session) -> None:
    for e in parse_catalog(CATALOG_SAMPLE):
        await upsert_entry(session, entry=e)
    await session.commit()
    out = await recommend_for_fan(session, fan_id=1, fan_type_lite="RISKY")
    assert out == []


async def test_recommend_newcomer_prefers_cheaper(session) -> None:
    for e in parse_catalog(CATALOG_SAMPLE):
        await upsert_entry(session, entry=e)
    await session.commit()
    out = await recommend_for_fan(session, fan_id=1, fan_type_lite="NEWCOMER")
    assert out
    # The starter set targets A1 newcomer explicitly → should be top.
    assert out[0].code == "02"


async def test_build_recommendation_returns_none_on_irrelevant_intent(session) -> None:
    for e in parse_catalog(CATALOG_SAMPLE):
        await upsert_entry(session, entry=e)
    await session.commit()
    settings = Settings(_env_file=None)
    out = await build_recommendation(
        session,
        fan_id=1,
        intent=Intent.GREETING,
        fan_type_lite="WHALE",
        fan_type_fine=None,
        settings=settings,
    )
    assert out is None


async def test_build_recommendation_creates_sales_attempt(session) -> None:
    for e in parse_catalog(CATALOG_SAMPLE):
        await upsert_entry(session, entry=e)
    await session.commit()
    settings = Settings(_env_file=None)
    out = await build_recommendation(
        session,
        fan_id=1,
        intent=Intent.CONTENT_REQUEST,
        fan_type_lite="WHALE",
        fan_type_fine=None,
        settings=settings,
    )
    assert out is not None
    assert out.invoice_payload.startswith("sonya:1:")
    assert out.dry_run is True  # no PAY_BOT_TOKEN

    rows = (await session.execute(select(SalesAttempt))).scalars().all()
    assert len(rows) == 1
    assert rows[0].outcome == SaleOutcome.SENT
    assert rows[0].fan_id == 1


async def test_register_invoice_request_logs_event(session) -> None:
    ev = await register_invoice_request(
        session,
        fan_id=1,
        invoice_payload="sonya:1:99:abc",
        sales_attempt_id=None,
        amount_stars=750,
    )
    assert ev.event_type == "invoice_created"
    assert ev.invoice_payload == "sonya:1:99:abc"

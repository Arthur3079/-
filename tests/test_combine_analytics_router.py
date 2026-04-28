"""Integration tests for the combine analytics FastAPI router."""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sonya.db.base import Base
from sonya.db.models_combine import (  # noqa: F401 — register tables
    Account,
    CommentingCampaign,
    Owner,
    Proxy,
    Reaction,
    ReactionCampaign,
    ReactionTarget,
)
from sonya_web.app import create_app
from sonya_web.deps import get_session


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> Generator[TestClient, None, None]:
    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _add_account(client: TestClient, phone: str) -> int:
    r = client.post(
        "/api/combine/accounts",
        json={"phone": phone, "api_id": 1, "api_hash": "h"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --------------------------- empty-state ---------------------------


def test_summary_empty_returns_zeros(client: TestClient) -> None:
    r = client.get("/api/combine/analytics/summary")
    assert r.status_code == 200
    body = r.json()

    for key in ("accounts", "warming", "parsers", "commenting", "reactions"):
        assert key in body, key

    assert body["accounts"]["total"] == 0
    assert body["warming"]["jobs_total"] == 0
    assert body["parsers"]["jobs_total"] == 0
    assert body["commenting"]["campaigns_total"] == 0
    assert body["reactions"]["campaigns_total"] == 0


@pytest.mark.parametrize(
    "path",
    [
        "/api/combine/analytics/accounts",
        "/api/combine/analytics/warming",
        "/api/combine/analytics/parsers",
        "/api/combine/analytics/commenting",
        "/api/combine/analytics/reactions",
    ],
)
def test_individual_endpoints_respond(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, dict)


# --------------------------- /summary equals composition ---------------------------


def test_summary_equals_individual_endpoints_after_writes(client: TestClient) -> None:
    aid = _add_account(client, "+10000000300")

    # commenting campaign so the dashboard top-list isn't empty
    r = client.post(
        "/api/combine/commenting/campaigns",
        json={
            "name": "C1",
            "target_channels": ["@news"],
            "account_ids": [aid],
            "prompt_template": "say {post}",
        },
    )
    assert r.status_code == 201, r.text

    # reaction campaign
    r = client.post(
        "/api/combine/reactions/campaigns",
        json={
            "name": "R1",
            "target_channels": ["@news"],
            "account_ids": [aid],
            "emojis": ["👍"],
            "accounts_per_post": 1,
        },
    )
    assert r.status_code == 201, r.text

    summary = client.get("/api/combine/analytics/summary").json()
    accounts = client.get("/api/combine/analytics/accounts").json()
    warming = client.get("/api/combine/analytics/warming").json()
    parsers = client.get("/api/combine/analytics/parsers").json()
    commenting = client.get("/api/combine/analytics/commenting").json()
    reactions = client.get("/api/combine/analytics/reactions").json()

    assert summary["accounts"] == accounts
    assert summary["warming"] == warming
    assert summary["parsers"] == parsers
    assert summary["commenting"] == commenting
    assert summary["reactions"] == reactions


# --------------------------- writes → reflected in /summary ---------------------------


def test_account_creation_reflected_in_summary(client: TestClient) -> None:
    before = client.get("/api/combine/analytics/accounts").json()
    assert before["total"] == 0

    _add_account(client, "+10000000301")
    _add_account(client, "+10000000302")

    after = client.get("/api/combine/analytics/accounts").json()
    assert after["total"] == 2
    by_status = {item["status"]: item["count"] for item in after["by_status"]}
    assert by_status["new"] == 2
    # zero-fill keeps every enum member present
    assert by_status["active"] == 0
    assert by_status["banned"] == 0


def test_proxy_creation_reflected_in_summary(client: TestClient) -> None:
    r = client.post(
        "/api/combine/proxies",
        json={
            "type": "socks5",
            "host": "1.2.3.4",
            "port": 1080,
        },
    )
    assert r.status_code == 201, r.text

    body = client.get("/api/combine/analytics/accounts").json()
    assert body["proxies_total"] == 1
    by_health = {item["status"]: item["count"] for item in body["proxies_by_health"]}
    assert by_health["unknown"] == 1


def test_reaction_campaign_lifecycle_reflected_in_top(client: TestClient) -> None:
    aid = _add_account(client, "+10000000303")
    r = client.post(
        "/api/combine/reactions/campaigns",
        json={
            "name": "Reactor",
            "target_channels": ["@news"],
            "account_ids": [aid],
            "emojis": ["👍"],
            "accounts_per_post": 1,
        },
    )
    cid = r.json()["id"]
    assert client.post(f"/api/combine/reactions/campaigns/{cid}/start").status_code == 200

    # push a target so it shows up in the targets count
    r = client.post(
        f"/api/combine/reactions/campaigns/{cid}/targets",
        json={"channel": "@news", "tg_message_id": 1},
    )
    assert r.status_code in (200, 201), r.text

    body = client.get("/api/combine/analytics/reactions").json()
    assert body["campaigns_total"] == 1
    by_status = {item["status"]: item["count"] for item in body["campaigns_by_status"]}
    assert by_status["running"] == 1
    assert body["targets_total"] == 1
    assert any(row["id"] == cid for row in body["top"])

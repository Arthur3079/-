"""Integration tests for the combine reactions FastAPI router."""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sonya.db.base import Base
from sonya.db.models_combine import (  # noqa: F401 — register tables
    Account,
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


def _account(client: TestClient, phone: str) -> int:
    r = client.post(
        "/api/combine/accounts",
        json={"phone": phone, "api_id": 1, "api_hash": "h"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _campaign(
    client: TestClient,
    *,
    name: str = "C",
    accounts: list[int] | None = None,
    channels: list[str] | None = None,
    emojis: list[str] | None = None,
    accounts_per_post: int = 3,
) -> dict:
    r = client.post(
        "/api/combine/reactions/campaigns",
        json={
            "name": name,
            "target_channels": channels if channels is not None else ["@news"],
            "account_ids": accounts if accounts is not None else [],
            "emojis": emojis if emojis is not None else ["👍", "🔥"],
            "accounts_per_post": accounts_per_post,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_create_campaign(client: TestClient) -> None:
    aid = _account(client, "+10000000200")
    body = _campaign(client, accounts=[aid])
    assert body["status"] == "draft"
    assert body["emojis"] == ["👍", "🔥"]
    assert body["accounts_per_post"] == 3


def test_create_rejects_unknown_accounts(client: TestClient) -> None:
    r = client.post(
        "/api/combine/reactions/campaigns",
        json={"name": "x", "account_ids": [9999], "emojis": ["👍"]},
    )
    assert r.status_code == 400


def test_start_requires_accounts_and_emojis(client: TestClient) -> None:
    aid = _account(client, "+10000000201")
    no_accounts = _campaign(client, accounts=[], emojis=["👍"])
    r = client.post(f"/api/combine/reactions/campaigns/{no_accounts['id']}/start")
    assert r.status_code == 400

    no_emojis = _campaign(client, accounts=[aid], emojis=[])
    r = client.post(f"/api/combine/reactions/campaigns/{no_emojis['id']}/start")
    assert r.status_code == 400


def test_lifecycle_start_pause_archive(client: TestClient) -> None:
    aid = _account(client, "+10000000202")
    cid = _campaign(client, accounts=[aid])["id"]

    r = client.post(f"/api/combine/reactions/campaigns/{cid}/start")
    assert r.json()["status"] == "running"
    r = client.post(f"/api/combine/reactions/campaigns/{cid}/pause")
    assert r.json()["status"] == "paused"
    r = client.post(f"/api/combine/reactions/campaigns/{cid}/archive")
    assert r.json()["status"] == "archived"
    r = client.post(f"/api/combine/reactions/campaigns/{cid}/start")
    assert r.status_code == 409


def test_push_target_dedupes(client: TestClient) -> None:
    aid = _account(client, "+10000000203")
    cid = _campaign(client, accounts=[aid])["id"]
    payload = {"channel": "@news", "tg_message_id": 7}
    r1 = client.post(f"/api/combine/reactions/campaigns/{cid}/targets", json=payload)
    r2 = client.post(f"/api/combine/reactions/campaigns/{cid}/targets", json=payload)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]


def test_push_target_unknown_channel(client: TestClient) -> None:
    aid = _account(client, "+10000000204")
    cid = _campaign(client, accounts=[aid])["id"]
    r = client.post(
        f"/api/combine/reactions/campaigns/{cid}/targets",
        json={"channel": "@stranger", "tg_message_id": 1},
    )
    assert r.status_code == 400


def test_plan_assigns_reactions(client: TestClient) -> None:
    a1 = _account(client, "+10000000205")
    a2 = _account(client, "+10000000206")
    a3 = _account(client, "+10000000207")
    cid = _campaign(client, accounts=[a1, a2, a3], emojis=["👍", "🔥"], accounts_per_post=2)["id"]
    tid = client.post(
        f"/api/combine/reactions/campaigns/{cid}/targets",
        json={"channel": "@news", "tg_message_id": 1},
    ).json()["id"]

    r = client.post(f"/api/combine/reactions/campaigns/{cid}/targets/{tid}/plan")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert {row["account_id"] for row in body} <= {a1, a2, a3}
    assert all(row["emoji"] in {"👍", "🔥"} for row in body)
    assert all(row["status"] == "pending" for row in body)

    # Target has moved to PLANNED.
    targets = client.get(f"/api/combine/reactions/campaigns/{cid}/targets").json()
    assert targets[0]["status"] == "planned"


def test_plan_is_idempotent(client: TestClient) -> None:
    aid = _account(client, "+10000000208")
    cid = _campaign(client, accounts=[aid], accounts_per_post=1)["id"]
    tid = client.post(
        f"/api/combine/reactions/campaigns/{cid}/targets",
        json={"channel": "@news", "tg_message_id": 1},
    ).json()["id"]
    p1 = client.post(f"/api/combine/reactions/campaigns/{cid}/targets/{tid}/plan").json()
    p2 = client.post(f"/api/combine/reactions/campaigns/{cid}/targets/{tid}/plan").json()
    assert {r["id"] for r in p1} == {r["id"] for r in p2}


def test_plan_with_empty_pool_400(client: TestClient) -> None:
    aid = _account(client, "+10000000209")
    cid = _campaign(client, accounts=[aid])["id"]
    tid = client.post(
        f"/api/combine/reactions/campaigns/{cid}/targets",
        json={"channel": "@news", "tg_message_id": 1},
    ).json()["id"]
    # Drop accounts via PATCH.
    client.patch(f"/api/combine/reactions/campaigns/{cid}", json={"account_ids": []})
    r = client.post(f"/api/combine/reactions/campaigns/{cid}/targets/{tid}/plan")
    assert r.status_code == 400


def test_record_outcome_advances_target(client: TestClient) -> None:
    a1 = _account(client, "+10000000210")
    a2 = _account(client, "+10000000211")
    cid = _campaign(client, accounts=[a1, a2], emojis=["👍"], accounts_per_post=2)["id"]
    tid = client.post(
        f"/api/combine/reactions/campaigns/{cid}/targets",
        json={"channel": "@news", "tg_message_id": 1},
    ).json()["id"]
    plan = client.post(f"/api/combine/reactions/campaigns/{cid}/targets/{tid}/plan").json()
    assert len(plan) == 2
    r1, r2 = plan

    # Record the first one — target stays PLANNED.
    r = client.post(
        f"/api/combine/reactions/campaigns/{cid}/targets/{tid}/reactions/{r1['id']}/record",
        json={"success": True},
    )
    assert r.status_code == 200 and r.json()["status"] == "posted"
    targets = client.get(f"/api/combine/reactions/campaigns/{cid}/targets").json()
    assert targets[0]["status"] == "planned"

    # Record the second one — target advances to DONE.
    r = client.post(
        f"/api/combine/reactions/campaigns/{cid}/targets/{tid}/reactions/{r2['id']}/record",
        json={"success": False, "error": "flood_wait"},
    )
    assert r.json()["status"] == "failed" and r.json()["error"] == "flood_wait"
    targets = client.get(f"/api/combine/reactions/campaigns/{cid}/targets").json()
    assert targets[0]["status"] == "done"


def test_record_twice_409(client: TestClient) -> None:
    aid = _account(client, "+10000000212")
    cid = _campaign(client, accounts=[aid], accounts_per_post=1)["id"]
    tid = client.post(
        f"/api/combine/reactions/campaigns/{cid}/targets",
        json={"channel": "@news", "tg_message_id": 1},
    ).json()["id"]
    rid = client.post(f"/api/combine/reactions/campaigns/{cid}/targets/{tid}/plan").json()[0]["id"]
    client.post(
        f"/api/combine/reactions/campaigns/{cid}/targets/{tid}/reactions/{rid}/record",
        json={"success": True},
    )
    r = client.post(
        f"/api/combine/reactions/campaigns/{cid}/targets/{tid}/reactions/{rid}/record",
        json={"success": True},
    )
    assert r.status_code == 409


def test_delete_campaign_cascades(client: TestClient) -> None:
    aid = _account(client, "+10000000213")
    cid = _campaign(client, accounts=[aid], accounts_per_post=1)["id"]
    tid = client.post(
        f"/api/combine/reactions/campaigns/{cid}/targets",
        json={"channel": "@news", "tg_message_id": 1},
    ).json()["id"]
    client.post(f"/api/combine/reactions/campaigns/{cid}/targets/{tid}/plan")
    r = client.delete(f"/api/combine/reactions/campaigns/{cid}")
    assert r.status_code == 204
    assert client.get(f"/api/combine/reactions/campaigns/{cid}").status_code == 404


def test_archived_campaign_rejects_target_push(client: TestClient) -> None:
    aid = _account(client, "+10000000214")
    cid = _campaign(client, accounts=[aid])["id"]
    client.post(f"/api/combine/reactions/campaigns/{cid}/archive")
    r = client.post(
        f"/api/combine/reactions/campaigns/{cid}/targets",
        json={"channel": "@news", "tg_message_id": 1},
    )
    assert r.status_code == 409


def test_list_campaigns(client: TestClient) -> None:
    aid = _account(client, "+10000000215")
    _campaign(client, name="r1", accounts=[aid])
    _campaign(client, name="r2", accounts=[aid])
    r = client.get("/api/combine/reactions/campaigns")
    assert {c["name"] for c in r.json()} == {"r1", "r2"}

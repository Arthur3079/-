"""Integration tests for the combine commenting FastAPI router."""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sonya.db.base import Base
from sonya.db.models_combine import (  # noqa: F401 — register tables
    Account,
    Comment,
    CommentingCampaign,
    ObservedPost,
    Owner,
    Proxy,
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


def _make_account(client: TestClient, phone: str) -> int:
    r = client.post(
        "/api/combine/accounts",
        json={"phone": phone, "api_id": 1, "api_hash": "h"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_campaign(
    client: TestClient,
    *,
    name: str = "campaign-1",
    accounts: list[int] | None = None,
    channels: list[str] | None = None,
    prompt: str = "Reply: {post}",
) -> dict:
    payload = {
        "name": name,
        "prompt_template": prompt,
        "target_channels": channels or ["@news"],
        "account_ids": accounts or [],
    }
    r = client.post("/api/combine/commenting/campaigns", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_campaign_starts_draft(client: TestClient) -> None:
    aid = _make_account(client, "+10000000100")
    body = _create_campaign(client, accounts=[aid])
    assert body["status"] == "draft"
    assert body["account_ids"] == [aid]
    assert body["target_channels"] == ["@news"]


def test_create_campaign_rejects_unknown_accounts(client: TestClient) -> None:
    r = client.post(
        "/api/combine/commenting/campaigns",
        json={
            "name": "x",
            "prompt_template": "y",
            "account_ids": [9999],
        },
    )
    assert r.status_code == 400


def test_create_rejects_inverted_delays(client: TestClient) -> None:
    r = client.post(
        "/api/combine/commenting/campaigns",
        json={
            "name": "x",
            "prompt_template": "y",
            "min_delay_seconds": 200,
            "max_delay_seconds": 100,
        },
    )
    assert r.status_code == 400


def test_start_requires_accounts(client: TestClient) -> None:
    body = _create_campaign(client, accounts=[])
    r = client.post(f"/api/combine/commenting/campaigns/{body['id']}/start")
    assert r.status_code == 400


def test_lifecycle_start_pause_archive(client: TestClient) -> None:
    aid = _make_account(client, "+10000000101")
    body = _create_campaign(client, accounts=[aid])
    cid = body["id"]

    r = client.post(f"/api/combine/commenting/campaigns/{cid}/start")
    assert r.json()["status"] == "running"
    assert r.json()["started_at"] is not None

    r = client.post(f"/api/combine/commenting/campaigns/{cid}/pause")
    assert r.json()["status"] == "paused"

    r = client.post(f"/api/combine/commenting/campaigns/{cid}/start")
    assert r.json()["status"] == "running"

    r = client.post(f"/api/combine/commenting/campaigns/{cid}/archive")
    assert r.json()["status"] == "archived"

    # Archived → 409 on every lifecycle action.
    r = client.post(f"/api/combine/commenting/campaigns/{cid}/start")
    assert r.status_code == 409


def test_update_campaign(client: TestClient) -> None:
    aid = _make_account(client, "+10000000102")
    cid = _create_campaign(client, accounts=[aid])["id"]
    r = client.patch(
        f"/api/combine/commenting/campaigns/{cid}",
        json={"name": "renamed", "max_comments_per_day": 50},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "renamed"
    assert r.json()["max_comments_per_day"] == 50


def test_push_post_dedupes_by_message_id(client: TestClient) -> None:
    aid = _make_account(client, "+10000000103")
    cid = _create_campaign(client, accounts=[aid])["id"]

    payload = {"channel": "@news", "tg_message_id": 42, "text": "post"}
    r1 = client.post(f"/api/combine/commenting/campaigns/{cid}/posts", json=payload)
    r2 = client.post(f"/api/combine/commenting/campaigns/{cid}/posts", json=payload)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]


def test_push_post_rejects_unknown_channel(client: TestClient) -> None:
    aid = _make_account(client, "+10000000104")
    cid = _create_campaign(client, accounts=[aid], channels=["@news"])["id"]
    r = client.post(
        f"/api/combine/commenting/campaigns/{cid}/posts",
        json={"channel": "@stranger", "tg_message_id": 1},
    )
    assert r.status_code == 400


def test_render_stub_creates_generated_comment(client: TestClient) -> None:
    aid = _make_account(client, "+10000000105")
    cid = _create_campaign(client, accounts=[aid])["id"]
    pid = client.post(
        f"/api/combine/commenting/campaigns/{cid}/posts",
        json={"channel": "@news", "tg_message_id": 1, "text": "hello"},
    ).json()["id"]

    r = client.post(
        f"/api/combine/commenting/campaigns/{cid}/posts/{pid}/render-stub",
        json={"account_id": aid},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "generated"
    assert "hello" in body["text"]

    # Post moves to QUEUED after the first generated comment.
    posts = client.get(f"/api/combine/commenting/campaigns/{cid}/posts").json()
    assert posts[0]["status"] == "queued"


def test_render_stub_rejects_account_outside_pool(client: TestClient) -> None:
    in_pool = _make_account(client, "+10000000106")
    other = _make_account(client, "+10000000107")
    cid = _create_campaign(client, accounts=[in_pool])["id"]
    pid = client.post(
        f"/api/combine/commenting/campaigns/{cid}/posts",
        json={"channel": "@news", "tg_message_id": 1},
    ).json()["id"]

    r = client.post(
        f"/api/combine/commenting/campaigns/{cid}/posts/{pid}/render-stub",
        json={"account_id": other},
    )
    assert r.status_code == 400


def test_record_comment_outcome_success(client: TestClient) -> None:
    aid = _make_account(client, "+10000000108")
    cid = _create_campaign(client, accounts=[aid])["id"]
    pid = client.post(
        f"/api/combine/commenting/campaigns/{cid}/posts",
        json={"channel": "@news", "tg_message_id": 7, "text": "hi"},
    ).json()["id"]
    comment_id = client.post(
        f"/api/combine/commenting/campaigns/{cid}/posts/{pid}/render-stub",
        json={"account_id": aid},
    ).json()["id"]

    r = client.post(
        f"/api/combine/commenting/campaigns/{cid}/posts/{pid}/comments/{comment_id}/record",
        json={"success": True, "tg_comment_id": 999},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "posted"
    assert body["tg_comment_id"] == 999
    # Post advances to COMMENTED on first successful record.
    posts = client.get(f"/api/combine/commenting/campaigns/{cid}/posts").json()
    assert posts[0]["status"] == "commented"


def test_record_comment_outcome_failure(client: TestClient) -> None:
    aid = _make_account(client, "+10000000109")
    cid = _create_campaign(client, accounts=[aid])["id"]
    pid = client.post(
        f"/api/combine/commenting/campaigns/{cid}/posts",
        json={"channel": "@news", "tg_message_id": 8, "text": "hi"},
    ).json()["id"]
    comment_id = client.post(
        f"/api/combine/commenting/campaigns/{cid}/posts/{pid}/render-stub",
        json={"account_id": aid},
    ).json()["id"]

    r = client.post(
        f"/api/combine/commenting/campaigns/{cid}/posts/{pid}/comments/{comment_id}/record",
        json={"success": False, "error": "flood_wait"},
    )
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"] == "flood_wait"

    # Recording twice → 409.
    r = client.post(
        f"/api/combine/commenting/campaigns/{cid}/posts/{pid}/comments/{comment_id}/record",
        json={"success": True},
    )
    assert r.status_code == 409


def test_delete_campaign_cascades(client: TestClient) -> None:
    aid = _make_account(client, "+10000000110")
    cid = _create_campaign(client, accounts=[aid])["id"]
    pid = client.post(
        f"/api/combine/commenting/campaigns/{cid}/posts",
        json={"channel": "@news", "tg_message_id": 9},
    ).json()["id"]
    client.post(
        f"/api/combine/commenting/campaigns/{cid}/posts/{pid}/render-stub",
        json={"account_id": aid},
    )

    r = client.delete(f"/api/combine/commenting/campaigns/{cid}")
    assert r.status_code == 204
    assert client.get(f"/api/combine/commenting/campaigns/{cid}").status_code == 404


def test_list_campaigns(client: TestClient) -> None:
    aid = _make_account(client, "+10000000111")
    _create_campaign(client, name="c1", accounts=[aid])
    _create_campaign(client, name="c2", accounts=[aid])
    r = client.get("/api/combine/commenting/campaigns")
    assert r.status_code == 200
    assert {c["name"] for c in r.json()} == {"c1", "c2"}

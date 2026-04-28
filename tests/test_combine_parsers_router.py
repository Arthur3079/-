"""Integration tests for the combine parsers FastAPI router."""

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
    ParserJob,
    ParserResult,
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


def _account(client: TestClient) -> int:
    r = client.post(
        "/api/combine/accounts",
        json={"phone": "+10000000088", "api_id": 1, "api_hash": "h"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_create_parser_job(client: TestClient) -> None:
    aid = _account(client)
    r = client.post(
        "/api/combine/parsers/jobs",
        json={
            "account_id": aid,
            "kind": "users_in_chat",
            "target": "telegram",
            "params": {"limit": 10},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["kind"] == "users_in_chat"
    assert body["target"] == "telegram"
    assert body["result_count"] == 0


def test_create_job_for_unknown_account_400(client: TestClient) -> None:
    r = client.post(
        "/api/combine/parsers/jobs",
        json={"account_id": 9999, "kind": "users_in_chat", "target": "x"},
    )
    assert r.status_code == 400


def test_run_stub_populates_results(client: TestClient) -> None:
    aid = _account(client)
    job_id = client.post(
        "/api/combine/parsers/jobs",
        json={"account_id": aid, "kind": "users_in_chat", "target": "telegram"},
    ).json()["id"]

    r = client.post(f"/api/combine/parsers/jobs/{job_id}/run-stub", json={"batch_size": 4})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["result_count"] == 4
    assert body["completed_at"] is not None

    page = client.get(f"/api/combine/parsers/jobs/{job_id}/results").json()
    assert page["total"] == 4
    assert len(page["items"]) == 4
    assert page["items"][0]["kind"] == "user"


def test_results_pagination(client: TestClient) -> None:
    aid = _account(client)
    job_id = client.post(
        "/api/combine/parsers/jobs",
        json={"account_id": aid, "kind": "chat_history", "target": "@news"},
    ).json()["id"]
    client.post(f"/api/combine/parsers/jobs/{job_id}/run-stub", json={"batch_size": 12})

    p1 = client.get(f"/api/combine/parsers/jobs/{job_id}/results?offset=0&limit=5").json()
    p2 = client.get(f"/api/combine/parsers/jobs/{job_id}/results?offset=5&limit=5").json()
    assert p1["total"] == 12 and len(p1["items"]) == 5
    assert p2["total"] == 12 and len(p2["items"]) == 5
    assert {i["id"] for i in p1["items"]}.isdisjoint({i["id"] for i in p2["items"]})


def test_push_results_marks_running_and_appends(client: TestClient) -> None:
    aid = _account(client)
    job_id = client.post(
        "/api/combine/parsers/jobs",
        json={"account_id": aid, "kind": "users_by_message", "target": "btc"},
    ).json()["id"]

    r = client.post(
        f"/api/combine/parsers/jobs/{job_id}/results",
        json={
            "results": [
                {"kind": "user", "tg_id": 1, "username": "alice"},
                {"kind": "user", "tg_id": 2, "username": "bob"},
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running"
    assert body["result_count"] == 2


def test_complete_then_push_returns_409(client: TestClient) -> None:
    aid = _account(client)
    job_id = client.post(
        "/api/combine/parsers/jobs",
        json={"account_id": aid, "kind": "users_in_chat", "target": "x"},
    ).json()["id"]

    client.post(f"/api/combine/parsers/jobs/{job_id}/complete", json={"success": True})
    r = client.post(
        f"/api/combine/parsers/jobs/{job_id}/results",
        json={"results": [{"kind": "user"}]},
    )
    assert r.status_code == 409


def test_cancel_is_idempotent(client: TestClient) -> None:
    aid = _account(client)
    job_id = client.post(
        "/api/combine/parsers/jobs",
        json={"account_id": aid, "kind": "users_in_chat", "target": "x"},
    ).json()["id"]
    r1 = client.post(f"/api/combine/parsers/jobs/{job_id}/cancel")
    r2 = client.post(f"/api/combine/parsers/jobs/{job_id}/cancel")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["status"] == "cancelled" and r2.json()["status"] == "cancelled"


def test_complete_with_failure_records_error(client: TestClient) -> None:
    aid = _account(client)
    job_id = client.post(
        "/api/combine/parsers/jobs",
        json={"account_id": aid, "kind": "users_in_chat", "target": "x"},
    ).json()["id"]
    r = client.post(
        f"/api/combine/parsers/jobs/{job_id}/complete",
        json={"success": False, "error": "flood_wait"},
    )
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"] == "flood_wait"


def test_delete_job_removes_results(client: TestClient) -> None:
    aid = _account(client)
    job_id = client.post(
        "/api/combine/parsers/jobs",
        json={"account_id": aid, "kind": "users_in_chat", "target": "x"},
    ).json()["id"]
    client.post(f"/api/combine/parsers/jobs/{job_id}/run-stub", json={})
    r = client.delete(f"/api/combine/parsers/jobs/{job_id}")
    assert r.status_code == 204
    assert client.get(f"/api/combine/parsers/jobs/{job_id}").status_code == 404


def test_list_jobs(client: TestClient) -> None:
    aid = _account(client)
    for kind in ("users_in_chat", "chat_history"):
        client.post(
            "/api/combine/parsers/jobs",
            json={"account_id": aid, "kind": kind, "target": "x"},
        )
    r = client.get("/api/combine/parsers/jobs")
    assert r.status_code == 200
    assert len(r.json()) == 2

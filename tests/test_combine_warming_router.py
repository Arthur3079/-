"""Integration tests for the combine warming FastAPI router."""

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
    WarmingAction,
    WarmingJob,
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


def _make_account(client: TestClient) -> int:
    r = client.post(
        "/api/combine/accounts",
        json={"phone": "+10000000077", "api_id": 1, "api_hash": "h"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_create_warming_job_uses_default_plan(client: TestClient) -> None:
    acc_id = _make_account(client)

    r = client.post("/api/combine/warming/jobs", json={"account_id": acc_id, "seed": 7})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["account_id"] == acc_id
    assert body["status"] == "pending"
    assert body["target_trust_score"] == 50
    assert body["total_actions"] >= 7  # at least 1/day × 7 days
    assert body["actions_pending"] == body["total_actions"]
    assert body["actions_done"] == 0


def test_create_warming_job_requires_existing_account(client: TestClient) -> None:
    r = client.post("/api/combine/warming/jobs", json={"account_id": 9999})
    assert r.status_code == 400


def test_warming_job_lifecycle(client: TestClient) -> None:
    acc_id = _make_account(client)
    r = client.post(
        "/api/combine/warming/jobs",
        json={
            "account_id": acc_id,
            "seed": 0,
            "plan": {
                "duration_days": 2,
                "actions_per_day_min": 1,
                "actions_per_day_max": 1,
                "target_trust_score": 5,
            },
        },
    )
    job = r.json()
    job_id = job["id"]
    assert job["total_actions"] == 2
    action_ids = [a["id"] for a in job["actions"]]

    # Pause + resume.
    r = client.post(f"/api/combine/warming/jobs/{job_id}/pause")
    assert r.json()["status"] == "paused"
    # Cannot complete an action while paused.
    r = client.post(
        f"/api/combine/warming/jobs/{job_id}/actions/{action_ids[0]}/complete",
        json={"success": True},
    )
    assert r.status_code == 409

    r = client.post(f"/api/combine/warming/jobs/{job_id}/resume")
    assert r.json()["status"] == "pending"

    # Complete first action.
    r = client.post(
        f"/api/combine/warming/jobs/{job_id}/actions/{action_ids[0]}/complete",
        json={"success": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done"

    # Detail view should show one done.
    r = client.get(f"/api/combine/warming/jobs/{job_id}")
    body = r.json()
    assert body["status"] == "running"
    assert body["actions_done"] == 1
    assert body["actions_pending"] == 1

    # Cannot complete the same action twice.
    r = client.post(
        f"/api/combine/warming/jobs/{job_id}/actions/{action_ids[0]}/complete",
        json={"success": True},
    )
    assert r.status_code == 409

    # Cancel the rest.
    r = client.post(f"/api/combine/warming/jobs/{job_id}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    # Cancel is idempotent.
    r = client.post(f"/api/combine/warming/jobs/{job_id}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_warming_job_detail_404(client: TestClient) -> None:
    r = client.get("/api/combine/warming/jobs/9999")
    assert r.status_code == 404


def test_warming_job_listed(client: TestClient) -> None:
    acc_id = _make_account(client)
    client.post("/api/combine/warming/jobs", json={"account_id": acc_id, "seed": 1})
    r = client.get("/api/combine/warming/jobs")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_warming_job_delete(client: TestClient) -> None:
    acc_id = _make_account(client)
    job_id = client.post(
        "/api/combine/warming/jobs", json={"account_id": acc_id, "seed": 2}
    ).json()["id"]

    r = client.delete(f"/api/combine/warming/jobs/{job_id}")
    assert r.status_code == 204
    r = client.get(f"/api/combine/warming/jobs/{job_id}")
    assert r.status_code == 404


def test_warming_failed_action_marks_failed_no_trust(client: TestClient) -> None:
    acc_id = _make_account(client)
    job = client.post(
        "/api/combine/warming/jobs",
        json={
            "account_id": acc_id,
            "seed": 9,
            "plan": {
                "duration_days": 1,
                "actions_per_day_min": 1,
                "actions_per_day_max": 1,
            },
        },
    ).json()
    aid = job["actions"][0]["id"]

    r = client.post(
        f"/api/combine/warming/jobs/{job['id']}/actions/{aid}/complete",
        json={"success": False, "error": "rate limited"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"] == "rate limited"

    # Account trust must NOT have moved.
    r = client.get(f"/api/combine/accounts/{acc_id}")
    assert r.json()["trust_score"] == 0

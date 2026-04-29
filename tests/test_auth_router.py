"""Integration tests for /api/auth/* endpoints + tenant isolation on combine routers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sonya.db.base import Base
from sonya.db.models_combine import (  # noqa: F401 — needed for metadata
    Account,
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
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    monkeypatch.setenv(
        "AUTH_JWT_SECRET",
        "test-secret-please-rotate-this-value-for-production-deploys",
    )
    monkeypatch.setenv("AUTH_REGISTER_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "abc")
    from sonya.config import get_settings

    get_settings.cache_clear()

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_register_returns_token(client: TestClient) -> None:
    r = client.post(
        "/api/auth/register",
        json={"login": "alice", "password": "supersecret123", "workspace_name": "alice-co"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


def test_register_rejects_duplicate_login(client: TestClient) -> None:
    payload = {"login": "bob", "password": "supersecret123"}
    r1 = client.post("/api/auth/register", json=payload)
    assert r1.status_code == 201
    r2 = client.post("/api/auth/register", json=payload)
    assert r2.status_code == 409


def test_register_rejects_short_password(client: TestClient) -> None:
    r = client.post(
        "/api/auth/register",
        json={"login": "user", "password": "short"},
    )
    assert r.status_code == 422


def test_login_with_valid_credentials(client: TestClient) -> None:
    client.post(
        "/api/auth/register",
        json={"login": "carol", "password": "supersecret123"},
    )
    r = client.post(
        "/api/auth/login",
        json={"login": "carol", "password": "supersecret123"},
    )
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_login_with_invalid_password(client: TestClient) -> None:
    client.post(
        "/api/auth/register",
        json={"login": "dave", "password": "supersecret123"},
    )
    r = client.post(
        "/api/auth/login",
        json={"login": "dave", "password": "wrong-password"},
    )
    assert r.status_code == 401


def test_login_with_nonexistent_user(client: TestClient) -> None:
    r = client.post(
        "/api/auth/login",
        json={"login": "ghost", "password": "anything-here"},
    )
    assert r.status_code == 401


def test_me_requires_token(client: TestClient) -> None:
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_with_token(client: TestClient) -> None:
    reg = client.post(
        "/api/auth/register",
        json={"login": "eve", "password": "supersecret123"},
    )
    token = reg.json()["access_token"]
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["login"] == "eve"
    assert body["role"] == "admin"
    assert body["owner_id"] >= 1


def test_me_rejects_invalid_token(client: TestClient) -> None:
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_combine_proxies_tenant_isolation(client: TestClient) -> None:
    """Two registered owners should not see each other's proxies."""
    # Register tenant A and create a proxy for them
    reg_a = client.post(
        "/api/auth/register",
        json={"login": "tenant-a", "password": "supersecret123", "workspace_name": "a"},
    )
    token_a = reg_a.json()["access_token"]
    r = client.post(
        "/api/combine/proxies",
        json={
            "host": "10.0.0.1",
            "port": 1080,
            "type": "socks5",
            "note": "proxy-a",
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 201, r.text

    # Register tenant B and verify they see no proxies
    reg_b = client.post(
        "/api/auth/register",
        json={"login": "tenant-b", "password": "supersecret123", "workspace_name": "b"},
    )
    token_b = reg_b.json()["access_token"]
    r = client.get(
        "/api/combine/proxies",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 200
    assert r.json() == []

    # Tenant A still sees their proxy
    r = client.get(
        "/api/combine/proxies",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["host"] == "10.0.0.1"


def test_combine_endpoints_work_without_auth_header(client: TestClient) -> None:
    """Backward compat: no Authorization header → falls back to DEFAULT_OWNER_ID."""
    r = client.get("/api/combine/proxies")
    assert r.status_code == 200
    assert r.json() == []

    r = client.post(
        "/api/combine/proxies",
        json={
            "host": "10.0.0.99",
            "port": 1080,
            "type": "socks5",
            "note": "legacy",
        },
    )
    assert r.status_code == 201

    r = client.get("/api/combine/proxies")
    assert r.status_code == 200
    assert len(r.json()) == 1

"""Integration tests for the combine FastAPI routers.

Uses an in-memory SQLite DB shared across requests via a single
:class:`AsyncSession` factory, and stubs out the Telethon-side login
manager with a fake client.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sonya.combine.accounts.login import LoginManager
from sonya.db.base import Base
from sonya.db.models_combine import (  # noqa: F401 — needed for metadata
    Account,
    Owner,
    Proxy,
)
from sonya_web.app import create_app
from sonya_web.deps import get_session
from sonya_web.routers import combine_accounts as combine_accounts_router
from tests.test_combine_login import FakeClient


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
def app_and_client(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[Any, TestClient, FakeClient], None, None]:
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "abc")
    from sonya.config import get_settings

    get_settings.cache_clear()

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    fake_client = FakeClient(scenario="no_2fa")

    def _factory(*, api_id: int, api_hash: str, proxy: Any) -> FakeClient:
        del api_id, api_hash, proxy
        return fake_client

    manager = LoginManager(client_factory=_factory)
    combine_accounts_router.set_login_manager(manager)

    app.dependency_overrides[get_session] = _override_session
    try:
        with TestClient(app) as client:
            yield app, client, fake_client
    finally:
        combine_accounts_router.set_login_manager(None)
        app.dependency_overrides.clear()
        get_settings.cache_clear()


# ---------- PROXY ROUTER ----------


def test_proxy_crud(app_and_client: tuple[Any, TestClient, FakeClient]) -> None:
    _, client, _ = app_and_client

    # initial list is empty
    r = client.get("/api/combine/proxies")
    assert r.status_code == 200
    assert r.json() == []

    payload = {
        "type": "socks5",
        "host": "proxy.example.com",
        "port": 1080,
        "username": "u",
        "password": "secret-password",
        "note": "primary",
    }
    r = client.post("/api/combine/proxies", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    proxy_id = body["id"]
    assert body["host"] == "proxy.example.com"
    # Password must NOT be returned in the response.
    assert "password" not in body
    assert body["has_password"] is True

    # duplicate (same owner+host+port+username) should 409
    r = client.post("/api/combine/proxies", json=payload)
    assert r.status_code == 409

    # patch
    r = client.patch(
        f"/api/combine/proxies/{proxy_id}",
        json={"note": "retired", "password": ""},
    )
    assert r.status_code == 200
    assert r.json()["note"] == "retired"
    assert r.json()["has_password"] is False

    # delete
    r = client.delete(f"/api/combine/proxies/{proxy_id}")
    assert r.status_code == 204
    r = client.get(f"/api/combine/proxies/{proxy_id}")
    assert r.status_code == 404


# ---------- ACCOUNT ROUTER ----------


def test_account_crud(app_and_client: tuple[Any, TestClient, FakeClient]) -> None:
    _, client, _ = app_and_client

    r = client.post(
        "/api/combine/accounts",
        json={"phone": "+10000000099", "role": "chatter", "api_id": 1, "api_hash": "h"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    acc_id = body["id"]
    assert body["phone"] == "+10000000099"
    assert body["has_session"] is False
    assert body["status"] == "new"

    # duplicate phone -> 409
    r = client.post(
        "/api/combine/accounts",
        json={"phone": "+10000000099", "role": "chatter"},
    )
    assert r.status_code == 409

    # invalid proxy_id -> 400
    r = client.post(
        "/api/combine/accounts",
        json={"phone": "+10000000100", "proxy_id": 9999},
    )
    assert r.status_code == 400

    # patch role
    r = client.patch(
        f"/api/combine/accounts/{acc_id}",
        json={"role": "commenter", "note": "for IG comments"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "commenter"
    assert r.json()["note"] == "for IG comments"

    # list
    r = client.get("/api/combine/accounts")
    assert r.status_code == 200
    assert len(r.json()) == 1

    # delete
    r = client.delete(f"/api/combine/accounts/{acc_id}")
    assert r.status_code == 204


def test_login_flow_no_2fa(app_and_client: tuple[Any, TestClient, FakeClient]) -> None:
    _, client, fake = app_and_client
    fake.scenario = "no_2fa"

    r = client.post(
        "/api/combine/accounts",
        json={"phone": "+10000000099", "api_id": 1, "api_hash": "h"},
    )
    acc_id = r.json()["id"]

    r = client.post(f"/api/combine/accounts/{acc_id}/login/start", json={})
    assert r.status_code == 200, r.text
    token = r.json()["login_token"]

    r = client.post(
        f"/api/combine/accounts/{acc_id}/login/code",
        json={"login_token": token, "code": "12345"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "done"
    assert body["account"]["has_session"] is True
    assert body["account"]["status"] == "active"
    assert body["account"]["tg_user_id"] == 42
    assert body["account"]["username"] == "alice"


def test_login_flow_with_2fa(app_and_client: tuple[Any, TestClient, FakeClient]) -> None:
    _, client, fake = app_and_client
    fake.scenario = "needs_2fa"

    r = client.post(
        "/api/combine/accounts",
        json={"phone": "+10000000077", "api_id": 1, "api_hash": "h"},
    )
    acc_id = r.json()["id"]

    r = client.post(f"/api/combine/accounts/{acc_id}/login/start", json={})
    token = r.json()["login_token"]

    r = client.post(
        f"/api/combine/accounts/{acc_id}/login/code",
        json={"login_token": token, "code": "12345"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "password_required"
    assert r.json()["account"] is None

    fake.scenario = "no_2fa"
    r = client.post(
        f"/api/combine/accounts/{acc_id}/login/password",
        json={"login_token": token, "password": "hunter2"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done"
    assert r.json()["account"]["has_session"] is True


def test_login_wrong_code_returns_400(app_and_client: tuple[Any, TestClient, FakeClient]) -> None:
    _, client, fake = app_and_client
    fake.scenario = "wrong_code"

    r = client.post(
        "/api/combine/accounts",
        json={"phone": "+10000000088", "api_id": 1, "api_hash": "h"},
    )
    acc_id = r.json()["id"]

    r = client.post(f"/api/combine/accounts/{acc_id}/login/start", json={})
    token = r.json()["login_token"]

    r = client.post(
        f"/api/combine/accounts/{acc_id}/login/code",
        json={"login_token": token, "code": "00000"},
    )
    assert r.status_code == 400


def test_login_start_requires_credentials(
    app_and_client: tuple[Any, TestClient, FakeClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client, _ = app_and_client

    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    from sonya.config import get_settings

    get_settings.cache_clear()

    r = client.post("/api/combine/accounts", json={"phone": "+10000000044"})
    acc_id = r.json()["id"]

    r = client.post(f"/api/combine/accounts/{acc_id}/login/start", json={})
    assert r.status_code == 400


def test_import_session(app_and_client: tuple[Any, TestClient, FakeClient]) -> None:
    _, client, _ = app_and_client

    r = client.post(
        "/api/combine/accounts",
        json={"phone": "+10000000033", "api_id": 1, "api_hash": "h"},
    )
    acc_id = r.json()["id"]

    r = client.post(
        f"/api/combine/accounts/{acc_id}/import_session",
        json={"session": "SOME_TELETHON_STRING_SESSION"},
    )
    assert r.status_code == 200
    assert r.json()["has_session"] is True
    assert r.json()["status"] == "active"


def test_logout(app_and_client: tuple[Any, TestClient, FakeClient]) -> None:
    _, client, _ = app_and_client

    r = client.post(
        "/api/combine/accounts",
        json={"phone": "+10000000022", "api_id": 1, "api_hash": "h"},
    )
    acc_id = r.json()["id"]
    client.post(
        f"/api/combine/accounts/{acc_id}/import_session",
        json={"session": "X"},
    )
    r = client.post(f"/api/combine/accounts/{acc_id}/logout")
    assert r.status_code == 200
    assert r.json()["has_session"] is False
    assert r.json()["status"] == "new"


def test_health_no_session(app_and_client: tuple[Any, TestClient, FakeClient]) -> None:
    _, client, _ = app_and_client
    r = client.post(
        "/api/combine/accounts",
        json={"phone": "+10000000011", "api_id": 1, "api_hash": "h"},
    )
    acc_id = r.json()["id"]

    r = client.post(f"/api/combine/accounts/{acc_id}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["is_authorized"] is False
    assert body["error"] == "no_session"

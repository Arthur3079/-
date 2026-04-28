"""Unit tests for `sonya.combine.accounts.login.LoginManager` with a fake client."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from sonya.combine.accounts.login import (
    CodeRequiredError,
    LoginExpired,
    LoginManager,
    PasswordRequiredError,
    health_check_account,
)
from sonya.db.models_combine import Account, AccountRole, AccountStatus


class FakeUser:
    def __init__(self, **kwargs: Any) -> None:
        self.id = kwargs.get("id")
        self.username = kwargs.get("username")
        self.first_name = kwargs.get("first_name")
        self.last_name = kwargs.get("last_name")


class FakeSentCode:
    def __init__(self, phone_code_hash: str = "fakehash") -> None:
        self.phone_code_hash = phone_code_hash


class _FakeSessionPasswordNeeded(Exception):
    pass


# Patch into the module namespace so `_is_password_needed_error` recognises it
# by class name.
_FakeSessionPasswordNeeded.__name__ = "SessionPasswordNeededError"


class FakeClient:
    def __init__(
        self,
        *,
        scenario: str = "no_2fa",
        session_string: str = "FAKE_SESSION_STRING",
        me: FakeUser | None = None,
    ) -> None:
        self.scenario = scenario
        self._session_string = session_string
        self._me = me or FakeUser(id=42, username="alice", first_name="Al", last_name="Ice")
        self.connected = False
        self.disconnected = False
        self.code_calls = 0
        self.password_calls = 0

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def send_code_request(self, phone: str) -> FakeSentCode:
        del phone
        return FakeSentCode("hash-ok")

    async def sign_in(
        self,
        phone: str | None = None,
        code: str | None = None,
        *,
        phone_code_hash: str | None = None,
    ) -> Any:
        del phone, phone_code_hash
        self.code_calls += 1
        if self.scenario == "wrong_code":
            raise RuntimeError("PHONE_CODE_INVALID")
        if self.scenario == "needs_2fa":
            raise _FakeSessionPasswordNeeded("2FA")
        return self._me

    async def sign_in_password(self, password: str) -> Any:
        del password
        self.password_calls += 1
        if self.scenario == "wrong_password":
            raise RuntimeError("PASSWORD_HASH_INVALID")
        return self._me

    async def get_me(self) -> FakeUser:
        return self._me

    def session_save(self) -> str:
        return self._session_string


def _account(account_id: int = 1) -> Account:
    acc = Account()
    acc.id = account_id
    acc.owner_id = 1
    acc.phone = "+10000000001"
    acc.role = AccountRole.MULTI
    acc.status = AccountStatus.NEW
    return acc


def _factory_for(client: FakeClient):  # type: ignore[no-untyped-def]
    def _make(*, api_id: int, api_hash: str, proxy: Any) -> FakeClient:
        del api_id, api_hash, proxy
        return client

    return _make


@pytest.mark.asyncio
async def test_login_happy_path_no_2fa() -> None:
    client = FakeClient(scenario="no_2fa")
    manager = LoginManager(client_factory=_factory_for(client))
    acc = _account()

    token, _ = await manager.start(account=acc, api_id=1, api_hash="h")
    assert client.connected is True

    identity = await manager.submit_code(login_token=token, code="12345")
    assert identity.session_string == "FAKE_SESSION_STRING"
    assert identity.tg_user_id == 42
    assert identity.username == "alice"
    # token consumed
    with pytest.raises(LoginExpired):
        await manager.submit_code(login_token=token, code="00000")


@pytest.mark.asyncio
async def test_login_2fa_path() -> None:
    client = FakeClient(scenario="needs_2fa")
    manager = LoginManager(client_factory=_factory_for(client))
    acc = _account()

    token, _ = await manager.start(account=acc, api_id=1, api_hash="h")
    with pytest.raises(PasswordRequiredError):
        await manager.submit_code(login_token=token, code="12345")

    # Manager keeps the pending entry alive after a 2FA error.
    # Now the same client should accept the password — flip the scenario.
    client.scenario = "no_2fa"
    identity = await manager.submit_password(login_token=token, password="hunter2")
    assert identity.session_string == "FAKE_SESSION_STRING"
    assert client.password_calls == 1


@pytest.mark.asyncio
async def test_login_wrong_code_drops_token() -> None:
    client = FakeClient(scenario="wrong_code")
    manager = LoginManager(client_factory=_factory_for(client))
    acc = _account()
    token, _ = await manager.start(account=acc, api_id=1, api_hash="h")

    with pytest.raises(CodeRequiredError):
        await manager.submit_code(login_token=token, code="00000")

    # Token must be invalidated on a code-rejected error.
    with pytest.raises(LoginExpired):
        await manager.submit_code(login_token=token, code="11111")


@pytest.mark.asyncio
async def test_login_token_expires_with_ttl() -> None:
    client = FakeClient()
    manager = LoginManager(client_factory=_factory_for(client), ttl=timedelta(seconds=-1))
    acc = _account()

    token, _ = await manager.start(account=acc, api_id=1, api_hash="h")
    with pytest.raises(LoginExpired):
        await manager.submit_code(login_token=token, code="12345")


@pytest.mark.asyncio
async def test_login_cancel_drops_token_and_disconnects() -> None:
    client = FakeClient()
    manager = LoginManager(client_factory=_factory_for(client))
    acc = _account()

    token, _ = await manager.start(account=acc, api_id=1, api_hash="h")
    await manager.cancel(token)
    assert client.disconnected is True
    with pytest.raises(LoginExpired):
        await manager.submit_code(login_token=token, code="12345")


@pytest.mark.asyncio
async def test_health_check_authorized() -> None:
    client = FakeClient()
    # default Telethon clients have `is_user_authorized`; FakeClient doesn't,
    # so the helper assumes True (matches Telethon's "if connected, ask
    # get_me directly" fallback for stubs).
    acc = _account()
    res = await health_check_account(
        account=acc,
        api_id=1,
        api_hash="h",
        client_factory=_factory_for(client),
    )
    assert res.is_authorized is True
    assert res.tg_user_id == 42
    assert client.disconnected is True


@pytest.mark.asyncio
async def test_health_check_handles_connect_error() -> None:
    class BoomClient(FakeClient):
        async def connect(self) -> None:
            raise RuntimeError("nope")

    res = await health_check_account(
        account=_account(),
        api_id=1,
        api_hash="h",
        client_factory=_factory_for(BoomClient()),
    )
    assert res.is_authorized is False
    assert "nope" in (res.error or "")


@pytest.mark.asyncio
async def test_health_check_not_authorized() -> None:
    class UnauthorizedClient(FakeClient):
        async def is_user_authorized(self) -> bool:
            return False

    res = await health_check_account(
        account=_account(),
        api_id=1,
        api_hash="h",
        client_factory=_factory_for(UnauthorizedClient()),
    )
    assert res.is_authorized is False
    assert res.error == "not_authorized"

"""Unit tests for ``TelethonClientFactory``.

Telethon itself isn't installed everywhere these tests run — and even
when it is, we don't want to talk to real Telegram from CI. The factory
accepts an injectable ``_TelethonClasses`` so we feed it a fake
``TelegramClient`` constructor and inspect the args it receives.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from cryptography.fernet import Fernet

from sonya.combine.security import encrypt_str
from sonya.combine.worker.telethon_factory import (
    NoSessionError,
    TelethonClientFactory,
    _TelethonClasses,
)
from sonya.config import Settings
from sonya.db.models_combine import (
    Account,
    AccountStatus,
    Proxy,
    ProxyHealth,
    ProxyType,
)

# --------------------------- fakes ---------------------------


@dataclass
class _FakeStringSession:
    raw: str


@dataclass
class _FakeClient:
    session: _FakeStringSession
    api_id: int
    api_hash: str
    proxy: object | None


def _make_fake_classes() -> _TelethonClasses:
    def make_session(raw: str) -> _FakeStringSession:
        return _FakeStringSession(raw=raw)

    def make_client(
        session: _FakeStringSession,
        *,
        api_id: int,
        api_hash: str,
        proxy: object | None = None,
    ) -> _FakeClient:
        return _FakeClient(session=session, api_id=api_id, api_hash=api_hash, proxy=proxy)

    return _TelethonClasses(
        client=make_client,  # type: ignore[arg-type]
        string_session=make_session,  # type: ignore[arg-type]
    )


def _settings(
    *, api_id: int | None = None, api_hash: str | None = None, key: str | None = None
) -> Settings:
    return Settings(
        telegram_api_id=api_id,
        telegram_api_hash=api_hash,
        combine_secret_key=key,
    )


def _account(
    *,
    session_blob: bytes | None = None,
    api_id: int | None = 12345,
    api_hash: str | None = "h" * 32,
    phone: str = "+10000000999",
) -> Account:
    acc = Account(
        id=1,
        owner_id=1,
        phone=phone,
        status=AccountStatus.ACTIVE,
        api_id=api_id,
        api_hash=api_hash,
        session_blob=session_blob,
    )
    return acc


def _proxy(
    *,
    password: str | None = None,
    mtproto_secret: str | None = None,
    ptype: ProxyType = ProxyType.SOCKS5,
) -> Proxy:
    return Proxy(
        id=2,
        owner_id=1,
        type=ptype,
        host="proxy.example.com",
        port=1080,
        username="user",
        password=password,
        mtproto_secret=mtproto_secret,
        health=ProxyHealth.OK,
    )


# --------------------------- happy path ---------------------------


def test_make_client_passes_session_string_and_api(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = TelethonClientFactory(_settings(), telethon=_make_fake_classes())
    acc = _account(session_blob=b"SESSION_PAYLOAD")

    client = factory.make_client(acc)
    assert isinstance(client, _FakeClient)
    assert client.api_id == 12345
    assert client.api_hash == "h" * 32
    assert client.session.raw == "SESSION_PAYLOAD"
    assert client.proxy is None


def test_make_client_uses_global_api_when_account_missing() -> None:
    factory = TelethonClientFactory(
        _settings(api_id=99, api_hash="g" * 32), telethon=_make_fake_classes()
    )
    acc = _account(api_id=None, api_hash=None, session_blob=b"SS")
    client = factory.make_client(acc)
    assert client.api_id == 99
    assert client.api_hash == "g" * 32


# --------------------------- proxy ---------------------------


def test_make_client_attaches_socks5_proxy() -> None:
    factory = TelethonClientFactory(_settings(), telethon=_make_fake_classes())
    acc = _account(session_blob=b"SS")
    proxy = _proxy(password="plain_pwd")

    client = factory.make_client(acc, proxy)
    # SOCKS5 returns a 6-tuple — see sonya.combine.accounts.proxy.
    assert isinstance(client.proxy, tuple)
    assert client.proxy[0] == 2  # SOCKS5
    assert client.proxy[1] == "proxy.example.com"
    assert client.proxy[4] == "user"
    assert client.proxy[5] == "plain_pwd"


def test_make_client_decrypts_proxy_password(monkeypatch: pytest.MonkeyPatch) -> None:
    key = Fernet.generate_key().decode("utf-8")
    settings = _settings(key=key)

    monkeypatch.setattr("sonya.combine.security.get_settings", lambda: settings)
    encrypted = encrypt_str("super-secret", settings=settings)
    assert encrypted is not None
    proxy = _proxy(password=encrypted.decode("utf-8"))

    factory = TelethonClientFactory(settings, telethon=_make_fake_classes())
    acc = _account(session_blob=encrypt_str("SS-INNER", settings=settings))

    client = factory.make_client(acc, proxy)
    assert isinstance(client.proxy, tuple)
    assert client.proxy[5] == "super-secret"
    # Original ORM row must still hold the encrypted form.
    assert proxy.password == encrypted.decode("utf-8")


def test_make_client_with_mtproto_proxy() -> None:
    factory = TelethonClientFactory(_settings(), telethon=_make_fake_classes())
    acc = _account(session_blob=b"SS")
    proxy = _proxy(ptype=ProxyType.MTPROTO, mtproto_secret="deadbeef")

    client = factory.make_client(acc, proxy)
    assert isinstance(client.proxy, dict)
    assert client.proxy["proxy_type"] == "mtproto"
    assert client.proxy["secret"] == "deadbeef"


# --------------------------- error paths ---------------------------


def test_make_client_raises_when_session_blob_missing() -> None:
    factory = TelethonClientFactory(_settings(), telethon=_make_fake_classes())
    acc = _account(session_blob=None)
    with pytest.raises(NoSessionError):
        factory.make_client(acc)


def test_make_client_raises_when_no_api_creds() -> None:
    factory = TelethonClientFactory(_settings(), telethon=_make_fake_classes())
    acc = _account(api_id=None, api_hash=None, session_blob=b"SS")
    with pytest.raises(ValueError):
        factory.make_client(acc)


# --------------------------- lazy import ---------------------------


def test_default_factory_lazy_imports_telethon(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing the factory must not import telethon eagerly."""
    import sys

    # If telethon was already imported by a previous test, this is a no-op
    # check — at minimum ensure the *factory* construction doesn't bring it in
    # by inspecting that no new entry appears.
    before = "telethon" in sys.modules
    factory = TelethonClientFactory(_settings())
    after = "telethon" in sys.modules
    assert factory is not None
    if not before:
        assert not after

"""Unit tests for :class:`sonya.combine.accounts.ClientPool` and proxy helper.

All tests are fully synchronous apart from the pool itself (which is async);
they use a fake client factory so they exercise no Telethon / network I/O.
"""

from __future__ import annotations

import asyncio

import pytest

from sonya.combine.accounts.pool import ClientPool
from sonya.combine.accounts.proxy import build_telethon_proxy
from sonya.db.models_combine import Account, Proxy, ProxyType


class _FakeClient:
    """Minimal stand-in for ``telethon.TelegramClient``."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def connect(self) -> None:  # pragma: no cover - trivial
        self.connect_calls += 1

    async def disconnect(self) -> None:  # pragma: no cover - trivial
        self.disconnect_calls += 1


def _fake_account(account_id: int) -> Account:
    acc = Account()
    # bypass ORM defaults — we only need identity for these tests
    acc.id = account_id
    acc.owner_id = 1
    acc.phone = f"+100000000{account_id:02d}"
    return acc


@pytest.mark.asyncio
async def test_pool_creates_one_client_per_account() -> None:
    built: list[int] = []

    def factory(account: Account) -> _FakeClient:  # type: ignore[override]
        built.append(account.id)
        return _FakeClient(f"acc-{account.id}")

    pool = ClientPool(factory=factory)  # type: ignore[arg-type]
    acc = _fake_account(1)

    first = await pool.get(acc)
    second = await pool.get(acc)

    assert first is second, "expected the same PooledClient to be returned"
    assert built == [1], "factory must be invoked exactly once per account"
    assert len(pool) == 1

    await pool.close()


@pytest.mark.asyncio
async def test_pool_connect_is_concurrency_safe() -> None:
    def factory(account: Account) -> _FakeClient:  # type: ignore[override]
        return _FakeClient(f"acc-{account.id}")

    pool = ClientPool(factory=factory)  # type: ignore[arg-type]
    acc = _fake_account(7)

    results = await asyncio.gather(*(pool.get(acc) for _ in range(10)))
    fake = results[0].client
    assert all(r is results[0] for r in results)
    assert fake.connect_calls == 1, "connect() must be called exactly once"

    await pool.close()
    assert fake.disconnect_calls == 1


@pytest.mark.asyncio
async def test_pool_drop_disconnects_and_forgets() -> None:
    def factory(account: Account) -> _FakeClient:  # type: ignore[override]
        return _FakeClient(f"acc-{account.id}")

    pool = ClientPool(factory=factory)  # type: ignore[arg-type]
    acc = _fake_account(3)
    pooled = await pool.get(acc)

    await pool.drop(acc.id)
    assert len(pool) == 0
    assert pooled.client.disconnect_calls == 1  # type: ignore[union-attr]

    # dropping an unknown id is a no-op
    await pool.drop(9999)


def test_build_telethon_proxy_none_returns_none() -> None:
    assert build_telethon_proxy(None) is None


def test_build_telethon_proxy_socks5_tuple() -> None:
    proxy = Proxy()
    proxy.id = 1
    proxy.type = ProxyType.SOCKS5
    proxy.host = "proxy.example.com"
    proxy.port = 1080
    proxy.username = "u"
    proxy.password = "p"

    built = build_telethon_proxy(proxy)
    assert built is not None
    value = built.as_telethon_arg()
    assert isinstance(value, tuple)
    assert value == (2, "proxy.example.com", 1080, True, "u", "p")


def test_build_telethon_proxy_mtproto_requires_secret() -> None:
    proxy = Proxy()
    proxy.id = 2
    proxy.type = ProxyType.MTPROTO
    proxy.host = "mt.example.com"
    proxy.port = 443
    proxy.mtproto_secret = None  # missing!

    with pytest.raises(ValueError, match="mtproto_secret"):
        build_telethon_proxy(proxy)


def test_build_telethon_proxy_mtproto_dict() -> None:
    proxy = Proxy()
    proxy.id = 3
    proxy.type = ProxyType.MTPROTO
    proxy.host = "mt.example.com"
    proxy.port = 443
    proxy.mtproto_secret = "dd" + "0" * 30

    built = build_telethon_proxy(proxy)
    assert built is not None
    value = built.as_telethon_arg()
    assert isinstance(value, dict)
    assert value == {
        "proxy_type": "mtproto",
        "addr": "mt.example.com",
        "port": 443,
        "secret": "dd" + "0" * 30,
    }

"""Async pool of Telethon clients keyed by account id.

Each managed account has its own ``TelegramClient`` instance backed by a
``StringSession`` stored in :class:`Account.session_blob`. The pool lazily
instantiates clients on first access, reuses the same client for subsequent
lookups, and cleanly disconnects all clients on :py:meth:`close`.

Sprint 0 provides the skeleton plus tests. The Sprint 1 CRUD layer will
actually populate ``session_blob`` via the login flow.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

from sonya.combine.accounts.proxy import build_telethon_proxy
from sonya.db.models_combine import Account

if TYPE_CHECKING:
    from telethon import TelegramClient


class ClientFactory(Protocol):
    """Builds a Telethon client for a given :class:`Account`.

    Injectable so tests can swap in a fake client without real Telethon
    network I/O.
    """

    def __call__(self, account: Account) -> TelegramClient: ...  # pragma: no cover


class PooledClient:
    """Wrapper around a Telethon client kept alive by :class:`ClientPool`.

    Public attributes are the minimum the rest of ``sonya.combine`` needs;
    callers can still reach :attr:`client` for raw Telethon access.
    """

    __slots__ = ("account_id", "client", "_connect_lock", "_connected")

    def __init__(self, account_id: int, client: TelegramClient) -> None:
        self.account_id = account_id
        self.client = client
        self._connect_lock = asyncio.Lock()
        self._connected = False

    async def ensure_connected(self) -> None:
        """Connect on first use; idempotent and concurrency-safe."""
        if self._connected:
            return
        async with self._connect_lock:
            if self._connected:
                return
            connect: Callable[..., Awaitable[Any]] = self.client.connect  # type: ignore[attr-defined]
            await connect()
            self._connected = True

    async def disconnect(self) -> None:
        if not self._connected:
            return
        disconnect: Callable[..., Awaitable[Any] | None] = self.client.disconnect  # type: ignore[attr-defined]
        result = disconnect()
        if asyncio.iscoroutine(result):
            await result
        self._connected = False


def _default_factory(account: Account) -> TelegramClient:
    """Default factory: build a real Telethon client from ``account``.

    Imported lazily so unit tests don't pay the cost of ``telethon`` at
    collection time.
    """

    from telethon import TelegramClient
    from telethon.sessions import StringSession

    if account.api_id is None or account.api_hash is None:
        raise ValueError(f"account {account.id}: api_id/api_hash required before it can connect")

    session = StringSession(account.session_blob.decode("utf-8") if account.session_blob else "")
    proxy = build_telethon_proxy(account.proxy)
    kwargs: dict[str, Any] = {}
    if proxy is not None:
        kwargs["proxy"] = proxy.as_telethon_arg()

    return TelegramClient(
        session=session,
        api_id=account.api_id,
        api_hash=account.api_hash,
        **kwargs,
    )


class ClientPool:
    """One Telethon client per account, created on demand, reused thereafter.

    Not a connection pool in the DB sense — each account legitimately needs a
    stable long-lived client. "Pool" just captures the lookup-by-id behaviour.
    """

    def __init__(self, factory: ClientFactory | None = None) -> None:
        self._factory: ClientFactory = factory or _default_factory
        self._clients: dict[int, PooledClient] = {}
        self._lock = asyncio.Lock()

    async def get(self, account: Account) -> PooledClient:
        """Return (creating if needed) a connected client for ``account``."""

        pooled = self._clients.get(account.id)
        if pooled is None:
            async with self._lock:
                pooled = self._clients.get(account.id)
                if pooled is None:
                    pooled = PooledClient(account.id, self._factory(account))
                    self._clients[account.id] = pooled
        await pooled.ensure_connected()
        return pooled

    async def drop(self, account_id: int) -> None:
        """Disconnect and forget one account."""
        pooled = self._clients.pop(account_id, None)
        if pooled is not None:
            await pooled.disconnect()

    async def close(self) -> None:
        """Disconnect every client; safe to call multiple times."""
        clients = list(self._clients.values())
        self._clients.clear()
        await asyncio.gather(
            *(c.disconnect() for c in clients),
            return_exceptions=True,
        )

    def __len__(self) -> int:
        return len(self._clients)


__all__ = ["ClientFactory", "ClientPool", "PooledClient"]

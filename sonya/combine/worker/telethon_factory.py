"""Build a real ``telethon.TelegramClient`` for a managed combine account.

The factory is deliberately tiny and side-effect-free: it does not
connect, sign in, or talk to Telegram. All it does is decrypt the
account's session blob, decrypt the proxy password, hand both to
``TelegramClient`` and return the unconnected instance. The caller
(plugin code) owns the lifecycle: ``await client.connect(); ...; await
client.disconnect()``.

Telethon is an optional import — the constructor accepts a
``client_class`` override so unit tests can plug in a tiny fake
without installing telethon. In production the default is
``telethon.TelegramClient`` and the session class is
``telethon.sessions.StringSession``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sonya.combine.accounts.proxy import build_telethon_proxy
from sonya.combine.accounts.repository import account_session_string
from sonya.combine.security import decrypt_str
from sonya.config import Settings, get_settings
from sonya.db.models_combine import Account, Proxy

if TYPE_CHECKING:  # pragma: no cover — type-only import
    from telethon import TelegramClient


class NoSessionError(RuntimeError):
    """Raised when an account has no session_blob to build a client from."""


SessionClass = Callable[[str], Any]
ClientClass = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class _TelethonClasses:
    """Lazy-imported Telethon constructors, packaged for dependency injection."""

    client: ClientClass
    string_session: SessionClass


def _import_telethon() -> _TelethonClasses:
    """Import ``telethon`` on first use so unit tests don't require it."""

    from telethon import TelegramClient
    from telethon.sessions import StringSession

    return _TelethonClasses(client=TelegramClient, string_session=StringSession)


def _decrypt_proxy_password(proxy: Proxy) -> Proxy:
    """Return a *shallow* copy of ``proxy`` with the password decrypted.

    The caller-friendly invariant is: rows on disk always store the
    encrypted form, but the value handed to Telethon is plain. We don't
    mutate the ORM row because doing so would persist plaintext on the
    next ``session.commit()``.
    """

    if not proxy.password:
        return proxy
    plain = decrypt_str(proxy.password.encode("utf-8"))
    if plain is None or plain == proxy.password:
        return proxy
    clone = Proxy(
        id=proxy.id,
        owner_id=proxy.owner_id,
        type=proxy.type,
        host=proxy.host,
        port=proxy.port,
        username=proxy.username,
        password=plain,
        mtproto_secret=proxy.mtproto_secret,
        health=proxy.health,
        last_checked_at=proxy.last_checked_at,
        latency_ms=proxy.latency_ms,
        note=proxy.note,
    )
    return clone


class TelethonClientFactory:
    """Materialise a ``TelegramClient`` from an :class:`Account` row."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        telethon: _TelethonClasses | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        # ``telethon`` is injected in tests; in prod we lazy-import on first use.
        self._telethon = telethon

    def _classes(self) -> _TelethonClasses:
        if self._telethon is None:
            self._telethon = _import_telethon()
        return self._telethon

    def make_client(self, account: Account, proxy: Proxy | None = None) -> TelegramClient:
        """Return an *unconnected* ``TelegramClient`` for ``account``.

        Raises:
            NoSessionError: account has no stored session.
            ValueError: account has no api_id/api_hash and the global
                settings don't carry a default either.
        """

        if not account.session_blob:
            raise NoSessionError(f"account {account.id} ({account.phone}) has no session_blob")

        api_id = account.api_id or self._settings.telegram_api_id
        api_hash = account.api_hash or self._settings.telegram_api_hash
        if not api_id or not api_hash:
            raise ValueError(
                f"account {account.id}: api_id/api_hash not set on the row "
                "and no global telegram_api_id/telegram_api_hash configured"
            )

        session_str = account_session_string(account)
        if session_str is None:
            raise NoSessionError(f"account {account.id}: session_blob could not be decrypted")

        proxy_for_telethon = _decrypt_proxy_password(proxy) if proxy is not None else None
        proxy_arg = build_telethon_proxy(proxy_for_telethon)

        cls = self._classes()
        return cls.client(
            cls.string_session(session_str),
            api_id=api_id,
            api_hash=api_hash,
            proxy=proxy_arg.as_telethon_arg() if proxy_arg is not None else None,
        )


__all__ = ["NoSessionError", "TelethonClientFactory"]

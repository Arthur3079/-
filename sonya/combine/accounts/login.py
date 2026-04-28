"""Telethon-based login flow for the combine ``Account`` rows.

A login is a multi-step state machine spread across several HTTP calls:

    /login/start    -> Telegram sends an SMS / app code, we keep the
                       partially-connected ``TelegramClient`` in memory.
    /login/code     -> user submits the code; if 2FA is on we ask for
                       a password, otherwise we save the session.
    /login/password -> user submits the cloud password (2FA), we save
                       the session.

State for a flow is identified by an opaque ``login_token`` that the
client must send back on every step. The server keeps the partial
client in :class:`LoginManager` and discards it after success / error /
timeout.

The flow is async and uses a real ``TelegramClient`` by default, but the
:class:`ClientFactory` callable is injectable so unit tests can plug in a
deterministic fake.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Protocol

from sonya.combine.accounts.proxy import build_telethon_proxy
from sonya.config import Settings, get_settings
from sonya.db.models_combine import Account, Proxy

if TYPE_CHECKING:
    from telethon import TelegramClient


# How long a partially-completed login is kept in memory before we drop it.
DEFAULT_TTL = timedelta(minutes=10)


class LoginError(RuntimeError):
    """Login flow could not be completed (wrong code, expired token, etc)."""


class LoginExpired(LoginError):
    """The login token was unknown or its TTL elapsed."""


class CodeRequiredError(LoginError):
    """The code provided was rejected by Telegram."""


class PasswordRequiredError(LoginError):
    """Telegram returned SessionPasswordNeededError — call /login/password."""


@dataclass
class LoginIdentity:
    tg_user_id: int | None
    username: str | None
    first_name: str | None
    last_name: str | None
    session_string: str


class LoginClient(Protocol):
    """Subset of ``telethon.TelegramClient`` used by the flow.

    Letting tests stub this lets us avoid spinning up real Telegram I/O.
    """

    async def connect(self) -> None: ...

    async def disconnect(self) -> None | Awaitable[None]: ...

    async def send_code_request(self, phone: str) -> Any: ...

    async def sign_in(
        self,
        phone: str | None = None,
        code: str | None = None,
        *,
        phone_code_hash: str | None = None,
    ) -> Any: ...

    async def sign_in_password(self, password: str) -> Any: ...

    async def get_me(self) -> Any: ...

    def session_save(self) -> str: ...


class ClientFactory(Protocol):
    def __call__(
        self, *, api_id: int, api_hash: str, proxy: Proxy | None
    ) -> LoginClient: ...  # pragma: no cover


def _default_factory(
    *, api_id: int, api_hash: str, proxy: Proxy | None
) -> LoginClient:  # pragma: no cover - thin telethon wrapper
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    session = StringSession()
    proxy_arg = build_telethon_proxy(proxy)
    kwargs: dict[str, Any] = {}
    if proxy_arg is not None:
        kwargs["proxy"] = proxy_arg.as_telethon_arg()
    return _TelethonAdapter(
        TelegramClient(session=session, api_id=api_id, api_hash=api_hash, **kwargs)
    )


class _TelethonAdapter:  # pragma: no cover - thin telethon wrapper
    """Adapt :class:`telethon.TelegramClient` to :class:`LoginClient`."""

    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    async def connect(self) -> None:
        await self._client.connect()  # type: ignore[func-returns-value]

    async def disconnect(self) -> None:
        result = self._client.disconnect()
        if asyncio.iscoroutine(result):
            await result

    async def send_code_request(self, phone: str) -> Any:
        return await self._client.send_code_request(phone)

    async def sign_in(
        self,
        phone: str | None = None,
        code: str | None = None,
        *,
        phone_code_hash: str | None = None,
    ) -> Any:
        return await self._client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)

    async def sign_in_password(self, password: str) -> Any:
        return await self._client.sign_in(password=password)

    async def get_me(self) -> Any:
        return await self._client.get_me()

    def session_save(self) -> str:
        return self._client.session.save()


# ---------- IN-MEMORY MANAGER ----------


@dataclass
class _PendingLogin:
    account_id: int
    phone: str
    client: LoginClient
    phone_code_hash: str | None
    expires_at: datetime


class LoginManager:
    """Holds partial logins keyed by an opaque ``login_token``.

    The manager is single-process by design; in a multi-worker deployment
    every worker keeps its own pool, which is fine because the token is
    server-side opaque and the same client must complete the flow that
    started it.
    """

    def __init__(
        self,
        *,
        client_factory: ClientFactory | None = None,
        ttl: timedelta = DEFAULT_TTL,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._factory: ClientFactory = client_factory or _default_factory
        self._ttl = ttl
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(24))
        self._pending: dict[str, _PendingLogin] = {}
        self._lock = asyncio.Lock()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def _gc(self) -> None:
        now = self._now()
        expired = [t for t, p in self._pending.items() if p.expires_at <= now]
        for token in expired:
            await self._drop(token)

    async def _drop(self, token: str) -> None:
        pending = self._pending.pop(token, None)
        if pending is None:
            return
        try:
            await pending.client.disconnect()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass

    async def start(
        self,
        *,
        account: Account,
        api_id: int,
        api_hash: str,
        settings: Settings | None = None,
    ) -> tuple[str, datetime]:
        """Create a new pending login, ask Telegram to send a code.

        Returns ``(login_token, expires_at)``.
        """

        del settings  # reserved for future per-call overrides
        async with self._lock:
            await self._gc()

        client = self._factory(api_id=api_id, api_hash=api_hash, proxy=account.proxy)
        await client.connect()
        try:
            sent = await client.send_code_request(account.phone)
        except Exception:
            await client.disconnect()
            raise

        phone_code_hash = getattr(sent, "phone_code_hash", None)
        token = self._token_factory()
        expires_at = self._now() + self._ttl
        async with self._lock:
            self._pending[token] = _PendingLogin(
                account_id=account.id,
                phone=account.phone,
                client=client,
                phone_code_hash=phone_code_hash,
                expires_at=expires_at,
            )
        return token, expires_at

    async def submit_code(self, *, login_token: str, code: str) -> LoginIdentity:
        """Submit the SMS / app code.

        Raises:
            LoginExpired:           token unknown or TTL hit.
            PasswordRequiredError:  account has 2FA enabled — call submit_password.
            CodeRequiredError:      Telegram rejected the code.
        """

        pending = self._get_pending(login_token)
        try:
            await pending.client.sign_in(
                phone=pending.phone,
                code=code,
                phone_code_hash=pending.phone_code_hash,
            )
        except Exception as exc:
            if _is_password_needed_error(exc):
                # Keep the pending entry alive; user must call /login/password.
                raise PasswordRequiredError("2FA password required") from exc
            await self._drop(login_token)
            raise CodeRequiredError(str(exc) or "code rejected") from exc

        identity = await self._capture_identity(pending)
        await self._drop(login_token)
        return identity

    async def submit_password(self, *, login_token: str, password: str) -> LoginIdentity:
        pending = self._get_pending(login_token)
        try:
            await pending.client.sign_in_password(password)
        except Exception as exc:
            await self._drop(login_token)
            raise CodeRequiredError(str(exc) or "password rejected") from exc

        identity = await self._capture_identity(pending)
        await self._drop(login_token)
        return identity

    async def cancel(self, login_token: str) -> None:
        await self._drop(login_token)

    def _get_pending(self, login_token: str) -> _PendingLogin:
        pending = self._pending.get(login_token)
        if pending is None or pending.expires_at <= self._now():
            raise LoginExpired("login token unknown or expired")
        return pending

    async def _capture_identity(self, pending: _PendingLogin) -> LoginIdentity:
        me = await pending.client.get_me()
        session_string = pending.client.session_save()
        return LoginIdentity(
            tg_user_id=getattr(me, "id", None),
            username=getattr(me, "username", None),
            first_name=getattr(me, "first_name", None),
            last_name=getattr(me, "last_name", None),
            session_string=session_string,
        )


def _is_password_needed_error(exc: BaseException) -> bool:
    """Return True if ``exc`` is Telethon's SessionPasswordNeededError."""
    name = type(exc).__name__
    if name == "SessionPasswordNeededError":
        return True
    try:
        from telethon.errors import SessionPasswordNeededError  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - telethon may not be installed in some envs
        return False
    return isinstance(exc, SessionPasswordNeededError)


# ---------- HEALTH CHECK (separate from login) ----------


@dataclass
class HealthResult:
    is_authorized: bool
    tg_user_id: int | None
    username: str | None
    error: str | None


async def health_check_account(
    *,
    account: Account,
    api_id: int,
    api_hash: str,
    client_factory: Callable[..., LoginClient] | None = None,
) -> HealthResult:
    """Connect with the stored session and ask Telegram who we are.

    Returns a :class:`HealthResult` — never raises (errors are reported
    via ``error``).
    """

    factory = client_factory or _default_factory
    client = factory(api_id=api_id, api_hash=api_hash, proxy=account.proxy)
    try:
        await client.connect()
        try:
            is_authorized = await _safe_is_authorized(client)
            if not is_authorized:
                return HealthResult(False, None, None, error="not_authorized")
            me = await client.get_me()
            return HealthResult(
                is_authorized=True,
                tg_user_id=getattr(me, "id", None),
                username=getattr(me, "username", None),
                error=None,
            )
        finally:
            try:
                await client.disconnect()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
    except Exception as exc:
        return HealthResult(False, None, None, error=str(exc) or type(exc).__name__)


async def _safe_is_authorized(client: LoginClient) -> bool:
    is_auth = getattr(client, "is_user_authorized", None)
    if is_auth is None:
        return True
    res = is_auth()
    if asyncio.iscoroutine(res):
        return bool(await res)
    return bool(res)


def resolve_telethon_credentials(
    account: Account,
    *,
    settings: Settings | None = None,
    api_id_override: int | None = None,
    api_hash_override: str | None = None,
) -> tuple[int, str]:
    """Find the api_id / api_hash to use for ``account``.

    Priority: explicit override > stored on the account > global settings.
    Raises ``ValueError`` if none are available.
    """

    cfg = settings or get_settings()
    api_id = api_id_override or account.api_id or cfg.telegram_api_id
    api_hash = api_hash_override or account.api_hash or cfg.telegram_api_hash
    if not api_id or not api_hash:
        raise ValueError(
            "no telegram api_id/api_hash available for account "
            f"{account.id}: set them on the account or in TELEGRAM_API_ID/TELEGRAM_API_HASH"
        )
    return int(api_id), str(api_hash)


__all__ = [
    "ClientFactory",
    "CodeRequiredError",
    "DEFAULT_TTL",
    "HealthResult",
    "LoginClient",
    "LoginError",
    "LoginExpired",
    "LoginIdentity",
    "LoginManager",
    "PasswordRequiredError",
    "health_check_account",
    "resolve_telethon_credentials",
]

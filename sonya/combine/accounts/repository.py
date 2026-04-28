"""Async DB CRUD helpers for combine accounts and proxies.

Single-owner deployment: every helper takes an explicit ``owner_id`` (which
defaults to 1 in the REST layer) so when multi-tenancy is flipped on the
queries already filter by it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.combine.security import decrypt_str, encrypt_str
from sonya.db.models_combine import (
    Account,
    AccountRole,
    AccountStatus,
    Owner,
    Proxy,
    ProxyHealth,
    ProxyType,
)

DEFAULT_OWNER_ID = 1


# ---------- OWNER ----------


async def ensure_default_owner(session: AsyncSession) -> Owner:
    """Make sure ``owners(id=1, name='default')`` exists. Idempotent."""

    owner = await session.get(Owner, DEFAULT_OWNER_ID)
    if owner is not None:
        return owner
    owner = Owner(id=DEFAULT_OWNER_ID, name="default")
    session.add(owner)
    await session.flush()
    return owner


# ---------- PROXY ----------


async def list_proxies(session: AsyncSession, *, owner_id: int = DEFAULT_OWNER_ID) -> list[Proxy]:
    res = await session.execute(
        select(Proxy).where(Proxy.owner_id == owner_id).order_by(Proxy.id.desc())
    )
    return list(res.scalars())


async def get_proxy(
    session: AsyncSession, proxy_id: int, *, owner_id: int = DEFAULT_OWNER_ID
) -> Proxy | None:
    proxy = await session.get(Proxy, proxy_id)
    if proxy is None or proxy.owner_id != owner_id:
        return None
    return proxy


async def create_proxy(
    session: AsyncSession,
    *,
    owner_id: int = DEFAULT_OWNER_ID,
    type: ProxyType,
    host: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
    mtproto_secret: str | None = None,
    note: str | None = None,
) -> Proxy:
    encrypted_password = encrypt_str(password)
    encrypted_password_str = (
        encrypted_password.decode("utf-8") if encrypted_password is not None else None
    )

    proxy = Proxy(
        owner_id=owner_id,
        type=type,
        host=host,
        port=port,
        username=username,
        password=encrypted_password_str,
        mtproto_secret=mtproto_secret,
        note=note,
        health=ProxyHealth.UNKNOWN,
    )
    session.add(proxy)
    await session.flush()
    return proxy


async def update_proxy(
    session: AsyncSession,
    proxy: Proxy,
    *,
    type: ProxyType | None = None,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    mtproto_secret: str | None = None,
    note: str | None = None,
) -> Proxy:
    if type is not None:
        proxy.type = type
    if host is not None:
        proxy.host = host
    if port is not None:
        proxy.port = port
    if username is not None:
        proxy.username = username or None
    if password is not None:
        encrypted = encrypt_str(password) if password else None
        proxy.password = encrypted.decode("utf-8") if encrypted is not None else None
    if mtproto_secret is not None:
        proxy.mtproto_secret = mtproto_secret or None
    if note is not None:
        proxy.note = note
    await session.flush()
    return proxy


async def delete_proxy(session: AsyncSession, proxy: Proxy) -> None:
    await session.delete(proxy)
    await session.flush()


def proxy_password_plaintext(proxy: Proxy) -> str | None:
    """Return the decrypted proxy password (or ``None``)."""
    if proxy.password is None:
        return None
    return decrypt_str(proxy.password.encode("utf-8"))


# ---------- ACCOUNT ----------


async def list_accounts(
    session: AsyncSession, *, owner_id: int = DEFAULT_OWNER_ID
) -> list[Account]:
    res = await session.execute(
        select(Account).where(Account.owner_id == owner_id).order_by(Account.id.desc())
    )
    return list(res.scalars())


async def get_account(
    session: AsyncSession, account_id: int, *, owner_id: int = DEFAULT_OWNER_ID
) -> Account | None:
    acc = await session.get(Account, account_id)
    if acc is None or acc.owner_id != owner_id:
        return None
    return acc


async def get_account_by_phone(
    session: AsyncSession, phone: str, *, owner_id: int = DEFAULT_OWNER_ID
) -> Account | None:
    res = await session.execute(
        select(Account).where(Account.owner_id == owner_id, Account.phone == phone)
    )
    return res.scalar_one_or_none()


async def create_account(
    session: AsyncSession,
    *,
    owner_id: int = DEFAULT_OWNER_ID,
    phone: str,
    role: AccountRole = AccountRole.MULTI,
    proxy_id: int | None = None,
    api_id: int | None = None,
    api_hash: str | None = None,
    note: str | None = None,
) -> Account:
    acc = Account(
        owner_id=owner_id,
        phone=phone,
        role=role,
        proxy_id=proxy_id,
        api_id=api_id,
        api_hash=api_hash,
        note=note,
        status=AccountStatus.NEW,
    )
    session.add(acc)
    await session.flush()
    return acc


async def update_account(
    session: AsyncSession,
    acc: Account,
    *,
    role: AccountRole | None = None,
    proxy_id: int | None = None,
    api_id: int | None = None,
    api_hash: str | None = None,
    note: str | None = None,
    is_enabled: bool | None = None,
    status: AccountStatus | None = None,
) -> Account:
    if role is not None:
        acc.role = role
    if proxy_id is not None:
        acc.proxy_id = proxy_id or None
    if api_id is not None:
        acc.api_id = api_id
    if api_hash is not None:
        acc.api_hash = api_hash or None
    if note is not None:
        acc.note = note
    if is_enabled is not None:
        acc.is_enabled = is_enabled
    if status is not None:
        acc.status = status
    await session.flush()
    return acc


async def set_account_session(
    session: AsyncSession,
    acc: Account,
    *,
    session_string: str,
    tg_user_id: int | None = None,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> Account:
    """Persist a Telethon ``StringSession`` and observed identity bits.

    The string is encrypted at rest (when a key is configured) and the
    account moves to ``ACTIVE`` status.
    """

    encrypted = encrypt_str(session_string)
    acc.session_blob = encrypted
    if tg_user_id is not None:
        acc.tg_user_id = tg_user_id
    if username is not None:
        acc.username = username
    if first_name is not None:
        acc.first_name = first_name
    if last_name is not None:
        acc.last_name = last_name
    acc.status = AccountStatus.ACTIVE
    acc.last_active_at = datetime.now(timezone.utc)
    await session.flush()
    return acc


async def clear_account_session(session: AsyncSession, acc: Account) -> Account:
    acc.session_blob = None
    acc.status = AccountStatus.NEW
    await session.flush()
    return acc


async def delete_account(session: AsyncSession, acc: Account) -> None:
    await session.delete(acc)
    await session.flush()


def account_session_string(acc: Account) -> str | None:
    """Return the decrypted Telethon ``StringSession`` text (or ``None``)."""
    if acc.session_blob is None:
        return None
    return decrypt_str(bytes(acc.session_blob))


__all__ = [
    "DEFAULT_OWNER_ID",
    "account_session_string",
    "clear_account_session",
    "create_account",
    "create_proxy",
    "delete_account",
    "delete_proxy",
    "ensure_default_owner",
    "get_account",
    "get_account_by_phone",
    "get_proxy",
    "list_accounts",
    "list_proxies",
    "proxy_password_plaintext",
    "set_account_session",
    "update_account",
    "update_proxy",
]

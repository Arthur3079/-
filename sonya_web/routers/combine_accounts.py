"""REST router for combine accounts — CRUD + Telethon login flow + health check.

Mounted at ``/api/combine/accounts``.

Login flow:
    1. POST /{id}/login/start    -> returns {login_token, expires_at}; Telegram sends code.
    2. POST /{id}/login/code     -> {login_token, code}; if 2FA, returns 409 password_required.
    3. POST /{id}/login/password -> {login_token, password}; finishes the flow.

Or import an existing session blob:
    POST /{id}/import_session -> {session: "<StringSession.save() output>"}.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.combine.accounts import login as login_mod
from sonya.combine.accounts import repository as repo
from sonya.combine.accounts.login import (
    CodeRequiredError,
    LoginExpired,
    LoginManager,
    PasswordRequiredError,
    health_check_account,
    resolve_telethon_credentials,
)
from sonya.combine.accounts.schemas import (
    AccountIn,
    AccountOut,
    AccountUpdate,
    HealthCheckOut,
    LoginCodeIn,
    LoginCodeOut,
    LoginPasswordIn,
    LoginPasswordOut,
    LoginStartIn,
    LoginStartOut,
    SessionImportIn,
)
from sonya.config import get_settings
from sonya.db.models_combine import Account, AccountStatus
from sonya_web.auth_deps import ensure_request_owner, get_current_owner_id
from sonya_web.deps import get_session

router = APIRouter(prefix="/combine/accounts", tags=["combine"])


# Process-wide singleton; tests can override via dependency injection.
_login_manager_singleton: LoginManager | None = None


def get_login_manager() -> LoginManager:
    global _login_manager_singleton
    if _login_manager_singleton is None:
        _login_manager_singleton = LoginManager()
    return _login_manager_singleton


def set_login_manager(manager: LoginManager | None) -> None:
    """Test hook: replace (or reset with ``None``) the singleton."""
    global _login_manager_singleton
    _login_manager_singleton = manager


def _to_out(acc: Account) -> AccountOut:
    return AccountOut(
        id=acc.id,
        owner_id=acc.owner_id,
        proxy_id=acc.proxy_id,
        phone=acc.phone,
        tg_user_id=acc.tg_user_id,
        username=acc.username,
        first_name=acc.first_name,
        last_name=acc.last_name,
        api_id=acc.api_id,
        has_session=acc.session_blob is not None,
        status=acc.status,
        role=acc.role,
        trust_score=acc.trust_score,
        last_active_at=acc.last_active_at,
        spam_block_until=acc.spam_block_until,
        flood_until=acc.flood_until,
        note=acc.note,
        is_enabled=acc.is_enabled,
    )


# ---------- CRUD ----------


@router.get("", response_model=list[AccountOut])
async def list_accounts(
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> list[AccountOut]:
    rows = await repo.list_accounts(session, owner_id=owner_id)
    return [_to_out(a) for a in rows]


@router.post("", response_model=AccountOut, status_code=201)
async def create_account(
    payload: AccountIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
    _owner: Annotated[object, Depends(ensure_request_owner)],
) -> AccountOut:
    if (
        payload.proxy_id is not None
        and await repo.get_proxy(session, payload.proxy_id, owner_id=owner_id) is None
    ):
        raise HTTPException(status_code=400, detail="proxy_id does not exist")
    try:
        acc = await repo.create_account(
            session,
            owner_id=owner_id,
            phone=payload.phone,
            role=payload.role,
            proxy_id=payload.proxy_id,
            api_id=payload.api_id,
            api_hash=payload.api_hash,
            note=payload.note,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="account with this phone exists") from exc
    return _to_out(acc)


@router.get("/{account_id}", response_model=AccountOut)
async def get_account(
    account_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> AccountOut:
    acc = await repo.get_account(session, account_id, owner_id=owner_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    return _to_out(acc)


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: int,
    payload: AccountUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> AccountOut:
    acc = await repo.get_account(session, account_id, owner_id=owner_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    if (
        payload.proxy_id is not None
        and payload.proxy_id != 0
        and await repo.get_proxy(session, payload.proxy_id, owner_id=owner_id) is None
    ):
        raise HTTPException(status_code=400, detail="proxy_id does not exist")
    acc = await repo.update_account(
        session,
        acc,
        role=payload.role,
        proxy_id=payload.proxy_id,
        api_id=payload.api_id,
        api_hash=payload.api_hash,
        note=payload.note,
        is_enabled=payload.is_enabled,
        status=payload.status,
    )
    await session.commit()
    return _to_out(acc)


@router.delete("/{account_id}", status_code=204)
async def delete_account(
    account_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> None:
    acc = await repo.get_account(session, account_id, owner_id=owner_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    await repo.delete_account(session, acc)
    await session.commit()


# ---------- LOGIN FLOW ----------


@router.post("/{account_id}/login/start", response_model=LoginStartOut)
async def login_start(
    account_id: int,
    payload: LoginStartIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    manager: Annotated[LoginManager, Depends(get_login_manager)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> LoginStartOut:
    acc = await repo.get_account(session, account_id, owner_id=owner_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    try:
        api_id, api_hash = resolve_telethon_credentials(
            acc,
            api_id_override=payload.api_id,
            api_hash_override=payload.api_hash,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        token, expires_at = await manager.start(account=acc, api_id=api_id, api_hash=api_hash)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"telegram error: {exc}") from exc
    return LoginStartOut(login_token=token, expires_at=expires_at)


@router.post("/{account_id}/login/code", response_model=LoginCodeOut)
async def login_code(
    account_id: int,
    payload: LoginCodeIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    manager: Annotated[LoginManager, Depends(get_login_manager)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> LoginCodeOut:
    acc = await repo.get_account(session, account_id, owner_id=owner_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    try:
        identity = await manager.submit_code(login_token=payload.login_token, code=payload.code)
    except LoginExpired as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except PasswordRequiredError:
        return LoginCodeOut(status="password_required", account=None)
    except CodeRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    acc = await repo.set_account_session(
        session,
        acc,
        session_string=identity.session_string,
        tg_user_id=identity.tg_user_id,
        username=identity.username,
        first_name=identity.first_name,
        last_name=identity.last_name,
    )
    await session.commit()
    return LoginCodeOut(status="done", account=_to_out(acc))


@router.post("/{account_id}/login/password", response_model=LoginPasswordOut)
async def login_password(
    account_id: int,
    payload: LoginPasswordIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    manager: Annotated[LoginManager, Depends(get_login_manager)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> LoginPasswordOut:
    acc = await repo.get_account(session, account_id, owner_id=owner_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    try:
        identity = await manager.submit_password(
            login_token=payload.login_token, password=payload.password
        )
    except LoginExpired as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except CodeRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    acc = await repo.set_account_session(
        session,
        acc,
        session_string=identity.session_string,
        tg_user_id=identity.tg_user_id,
        username=identity.username,
        first_name=identity.first_name,
        last_name=identity.last_name,
    )
    await session.commit()
    return LoginPasswordOut(status="done", account=_to_out(acc))


@router.post("/{account_id}/login/cancel", status_code=204)
async def login_cancel(
    account_id: int,
    payload: LoginPasswordIn,  # only `login_token` is used; password ignored.
    manager: Annotated[LoginManager, Depends(get_login_manager)],
) -> None:
    del account_id
    await manager.cancel(payload.login_token)


@router.post("/{account_id}/import_session", response_model=AccountOut)
async def import_session(
    account_id: int,
    payload: SessionImportIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> AccountOut:
    acc = await repo.get_account(session, account_id, owner_id=owner_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    acc = await repo.set_account_session(session, acc, session_string=payload.session)
    await session.commit()
    return _to_out(acc)


@router.post("/{account_id}/logout", response_model=AccountOut)
async def logout_account(
    account_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> AccountOut:
    acc = await repo.get_account(session, account_id, owner_id=owner_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    acc = await repo.clear_account_session(session, acc)
    await session.commit()
    return _to_out(acc)


# ---------- HEALTH CHECK ----------


@router.post("/{account_id}/health", response_model=HealthCheckOut)
async def health_check(
    account_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> HealthCheckOut:
    acc = await repo.get_account(session, account_id, owner_id=owner_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")

    if acc.session_blob is None:
        return HealthCheckOut(
            id=acc.id,
            status=acc.status,
            is_authorized=False,
            error="no_session",
        )

    try:
        api_id, api_hash = resolve_telethon_credentials(acc, settings=get_settings())
    except ValueError as exc:
        return HealthCheckOut(id=acc.id, status=acc.status, is_authorized=False, error=str(exc))

    factory = _build_session_factory(repo.account_session_string(acc))
    result = await health_check_account(
        account=acc,
        api_id=api_id,
        api_hash=api_hash,
        client_factory=factory,
    )
    if result.is_authorized:
        if result.tg_user_id is not None:
            acc.tg_user_id = result.tg_user_id
        if result.username is not None:
            acc.username = result.username
        if acc.status == AccountStatus.NEW:
            acc.status = AccountStatus.ACTIVE
        from datetime import datetime, timezone

        acc.last_active_at = datetime.now(timezone.utc)
    elif acc.status == AccountStatus.ACTIVE and result.error == "not_authorized":
        # Session was revoked / expired — drop status back so the operator notices.
        acc.status = AccountStatus.NEW
    await session.commit()

    return HealthCheckOut(
        id=acc.id,
        status=acc.status,
        is_authorized=result.is_authorized,
        error=result.error,
        tg_user_id=result.tg_user_id,
        username=result.username,
    )


def _build_session_factory(session_string: str | None):  # type: ignore[no-untyped-def]
    """Return a factory that re-uses the stored session string."""

    def _factory(*, api_id: int, api_hash: str, proxy):  # type: ignore[no-untyped-def]
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        from sonya.combine.accounts.proxy import build_telethon_proxy

        proxy_arg = build_telethon_proxy(proxy)
        kwargs: dict[str, object] = {}
        if proxy_arg is not None:
            kwargs["proxy"] = proxy_arg.as_telethon_arg()
        client = TelegramClient(
            session=StringSession(session_string or ""),
            api_id=api_id,
            api_hash=api_hash,
            **kwargs,
        )
        return login_mod._TelethonAdapter(client)

    return _factory


__all__ = ["get_login_manager", "router", "set_login_manager"]

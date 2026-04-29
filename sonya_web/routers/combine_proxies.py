"""REST router for combine proxies — CRUD + connectivity probe.

Mounted at ``/api/combine/proxies``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.combine.accounts import repository as repo
from sonya.combine.accounts.schemas import (
    ProxyHealthOut,
    ProxyIn,
    ProxyOut,
    ProxyUpdate,
)
from sonya.db.models_combine import Proxy, ProxyHealth
from sonya_web.auth_deps import ensure_request_owner, get_current_owner_id
from sonya_web.deps import get_session

router = APIRouter(prefix="/combine/proxies", tags=["combine"])


def _to_out(proxy: Proxy) -> ProxyOut:
    return ProxyOut(
        id=proxy.id,
        owner_id=proxy.owner_id,
        type=proxy.type,
        host=proxy.host,
        port=proxy.port,
        username=proxy.username,
        has_password=bool(proxy.password),
        has_mtproto_secret=bool(proxy.mtproto_secret),
        health=proxy.health,
        last_checked_at=proxy.last_checked_at,
        latency_ms=proxy.latency_ms,
        note=proxy.note,
    )


@router.get("", response_model=list[ProxyOut])
async def list_proxies(
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> list[ProxyOut]:
    rows = await repo.list_proxies(session, owner_id=owner_id)
    return [_to_out(p) for p in rows]


@router.post("", response_model=ProxyOut, status_code=201)
async def create_proxy(
    payload: ProxyIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
    _owner: Annotated[object, Depends(ensure_request_owner)],
) -> ProxyOut:
    try:
        proxy = await repo.create_proxy(
            session,
            owner_id=owner_id,
            type=payload.type,
            host=payload.host,
            port=payload.port,
            username=payload.username,
            password=payload.password,
            mtproto_secret=payload.mtproto_secret,
            note=payload.note,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="proxy already exists") from exc
    return _to_out(proxy)


@router.get("/{proxy_id}", response_model=ProxyOut)
async def get_proxy(
    proxy_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> ProxyOut:
    proxy = await repo.get_proxy(session, proxy_id, owner_id=owner_id)
    if proxy is None:
        raise HTTPException(status_code=404, detail="proxy not found")
    return _to_out(proxy)


@router.patch("/{proxy_id}", response_model=ProxyOut)
async def update_proxy(
    proxy_id: int,
    payload: ProxyUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> ProxyOut:
    proxy = await repo.get_proxy(session, proxy_id, owner_id=owner_id)
    if proxy is None:
        raise HTTPException(status_code=404, detail="proxy not found")
    proxy = await repo.update_proxy(
        session,
        proxy,
        type=payload.type,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password,
        mtproto_secret=payload.mtproto_secret,
        note=payload.note,
    )
    await session.commit()
    return _to_out(proxy)


@router.delete("/{proxy_id}", status_code=204)
async def delete_proxy(
    proxy_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> None:
    proxy = await repo.get_proxy(session, proxy_id, owner_id=owner_id)
    if proxy is None:
        raise HTTPException(status_code=404, detail="proxy not found")
    await repo.delete_proxy(session, proxy)
    await session.commit()


@router.post("/{proxy_id}/check", response_model=ProxyHealthOut)
async def check_proxy(
    proxy_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> ProxyHealthOut:
    """Best-effort TCP connect probe — measures reachability + latency.

    A real proxy handshake (SOCKS5 auth, MTProto secret check) is out of
    scope here; we just confirm the host:port is reachable so the user
    sees broken entries quickly.
    """

    proxy = await repo.get_proxy(session, proxy_id, owner_id=owner_id)
    if proxy is None:
        raise HTTPException(status_code=404, detail="proxy not found")

    started = time.monotonic()
    error: str | None = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(proxy.host, proxy.port), timeout=5.0
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        del reader
    except Exception as exc:
        error = str(exc) or type(exc).__name__

    elapsed_ms = int((time.monotonic() - started) * 1000)
    if error is not None:
        proxy.health = ProxyHealth.DEAD
        proxy.latency_ms = None
    elif elapsed_ms > 1500:
        proxy.health = ProxyHealth.SLOW
        proxy.latency_ms = elapsed_ms
    else:
        proxy.health = ProxyHealth.OK
        proxy.latency_ms = elapsed_ms

    from datetime import datetime, timezone

    proxy.last_checked_at = datetime.now(timezone.utc)
    await session.commit()

    return ProxyHealthOut(
        id=proxy.id,
        health=proxy.health,
        latency_ms=proxy.latency_ms,
        error=error,
    )


__all__ = ["router"]

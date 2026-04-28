"""POST-эндпоинты для действий оператора (pause / resume / handoff / note).

Авторизации нет — это локальная панель. Действия пишутся в `admin_actions`
с `admin_user_id=0` (заглушка для веб-оператора).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.admin import repository as admin_repo
from sonya.crm import repository as crm_repo
from sonya_web.deps import get_session

router = APIRouter()

WEB_ADMIN_USER_ID = 0


class PauseRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=240)


class NoteRequest(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


@router.post("/clients/{fan_id}/pause")
async def pause(
    fan_id: int,
    body: PauseRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    client = await admin_repo.pause_client(session, fan_id=fan_id, reason=body.reason)
    if client is None:
        raise HTTPException(status_code=404, detail=f"Client {fan_id} not found")
    await admin_repo.log_action(
        session,
        admin_user_id=WEB_ADMIN_USER_ID,
        action_type="pause",
        target_fan_id=fan_id,
        payload=body.reason,
    )
    await session.commit()
    return {"ok": True, "is_paused": client.is_paused, "paused_reason": client.paused_reason}


@router.post("/clients/{fan_id}/resume")
async def resume(
    fan_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    client = await admin_repo.resume_client(session, fan_id=fan_id)
    if client is None:
        raise HTTPException(status_code=404, detail=f"Client {fan_id} not found")
    # Снимаем флаг handoff_required, если он был выставлен, — resume возвращает клиента
    # боту полностью.
    if client.handoff_required:
        await crm_repo.clear_handoff(session, fan_id=fan_id)
    await admin_repo.log_action(
        session,
        admin_user_id=WEB_ADMIN_USER_ID,
        action_type="resume",
        target_fan_id=fan_id,
    )
    await session.commit()
    return {
        "ok": True,
        "is_paused": client.is_paused,
        "handoff_required": client.handoff_required,
    }


@router.post("/clients/{fan_id}/handoff")
async def handoff(
    fan_id: int,
    body: PauseRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """Передаём клиента оператору: pause с префиксом `handoff:`
    + `handoff_required=True`, чтобы UI-бейдж и фильтр сработали.
    """
    client = await admin_repo.set_handoff(session, fan_id=fan_id, reason=body.reason)
    if client is None:
        raise HTTPException(status_code=404, detail=f"Client {fan_id} not found")
    if not client.handoff_required:
        await crm_repo.set_handoff_required(session, fan_id=fan_id, reason=body.reason)
    await admin_repo.log_action(
        session,
        admin_user_id=WEB_ADMIN_USER_ID,
        action_type="handoff",
        target_fan_id=fan_id,
        payload=body.reason,
    )
    await session.commit()
    return {
        "ok": True,
        "is_paused": client.is_paused,
        "paused_reason": client.paused_reason,
        "handoff_required": client.handoff_required,
    }


@router.post("/clients/{fan_id}/note")
async def add_note(
    fan_id: int,
    body: NoteRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    client = await admin_repo.update_notes(session, fan_id=fan_id, note=body.note)
    if client is None:
        raise HTTPException(status_code=404, detail=f"Client {fan_id} not found")
    await admin_repo.log_action(
        session,
        admin_user_id=WEB_ADMIN_USER_ID,
        action_type="note",
        target_fan_id=fan_id,
        payload=body.note[:240],
    )
    await session.commit()
    return {"ok": True, "notes": client.notes}

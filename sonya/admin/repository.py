"""DB access for admin operations.

Kept separate from the Telethon command layer so we can unit-test policy
logic (pause/resume/handoff/notes) without standing up a Telegram client.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import AdminAction, Client


async def log_action(
    session: AsyncSession,
    *,
    admin_user_id: int,
    action_type: str,
    target_fan_id: int | None = None,
    payload: str | None = None,
) -> AdminAction:
    """Append one row to `admin_actions`. Caller commits."""
    row = AdminAction(
        admin_user_id=admin_user_id,
        action_type=action_type,
        target_fan_id=target_fan_id,
        payload=payload,
        timestamp=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row


async def pause_client(
    session: AsyncSession,
    *,
    fan_id: int,
    reason: str | None = None,
) -> Client | None:
    res = await session.execute(select(Client).where(Client.fan_id == fan_id))
    client = res.scalar_one_or_none()
    if client is None:
        return None
    client.is_paused = True
    client.paused_reason = reason
    await session.flush()
    return client


async def resume_client(session: AsyncSession, *, fan_id: int) -> Client | None:
    res = await session.execute(select(Client).where(Client.fan_id == fan_id))
    client = res.scalar_one_or_none()
    if client is None:
        return None
    client.is_paused = False
    client.paused_reason = None
    await session.flush()
    return client


async def set_handoff(
    session: AsyncSession,
    *,
    fan_id: int,
    reason: str | None = None,
) -> Client | None:
    """Same as pause but tags the reason with `handoff:` prefix for filtering."""
    return await pause_client(
        session,
        fan_id=fan_id,
        reason=f"handoff:{reason}" if reason else "handoff",
    )


async def update_notes(
    session: AsyncSession,
    *,
    fan_id: int,
    note: str,
) -> Client | None:
    """Append `note` to `client.notes` (newline-separated)."""
    res = await session.execute(select(Client).where(Client.fan_id == fan_id))
    client = res.scalar_one_or_none()
    if client is None:
        return None
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    line = f"[{timestamp}] {note}"
    client.notes = f"{client.notes}\n{line}" if client.notes else line
    await session.flush()
    return client


async def list_recent_actions(
    session: AsyncSession,
    *,
    limit: int = 20,
) -> list[AdminAction]:
    res = await session.execute(
        select(AdminAction).order_by(AdminAction.timestamp.desc()).limit(limit)
    )
    return list(res.scalars().all())

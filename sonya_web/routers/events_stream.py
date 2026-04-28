"""SSE-канал: последние события из events_log.

Простой polling-based SSE: раз в N секунд читаем новые строки из
`events_log` и отправляем клиенту. Для локального MVP этого достаточно;
при необходимости позже заменим на in-process pub/sub.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select

from sonya.db.models import EventLog
from sonya.db.session import async_session_factory

router = APIRouter()

POLL_INTERVAL_SECONDS = 2.0


async def _event_stream() -> AsyncIterator[str]:
    factory = async_session_factory()
    last_id: int | None = None

    # Начинаем с самого свежего id, чтобы не отдавать всю историю при connect.
    async with factory() as session:
        latest = (
            await session.execute(select(EventLog.id).order_by(desc(EventLog.id)).limit(1))
        ).scalar_one_or_none()
        last_id = int(latest) if latest is not None else 0

    while True:
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(EventLog)
                        .where(EventLog.id > last_id)
                        .order_by(EventLog.id.asc())
                        .limit(50)
                    )
                )
                .scalars()
                .all()
            )

        for row in rows:
            last_id = max(last_id or 0, row.id)
            payload = {
                "id": row.id,
                "fan_id": row.fan_id,
                "event_type": row.event_type,
                "payload": row.payload,
                "timestamp": row.timestamp.isoformat(),
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        # Heartbeat — комментарий для прокси, чтобы не закрывали соединение.
        if not rows:
            yield ": ping\n\n"

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


@router.get("/events/stream")
async def stream_events() -> StreamingResponse:
    return StreamingResponse(_event_stream(), media_type="text/event-stream")

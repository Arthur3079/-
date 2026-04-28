"""Общие FastAPI-зависимости."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.session import async_session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a fresh `AsyncSession` per request, closing it after."""
    factory = async_session_factory()
    async with factory() as session:
        yield session

"""Telethon-backed :class:`ParserExecutor` implementation.

Translates each :class:`ParserKind` into the corresponding Telethon
``iter_*`` call and yields :class:`ExecutorResult` rows that the worker
plugin persists into ``combine_parser_results``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sonya.combine.parsers.executor import ExecutorResult
from sonya.db.models_combine import (
    Account,
    ParserJob,
    ParserKind,
    ParserResultKind,
)

if TYPE_CHECKING:  # pragma: no cover — type-only import
    from telethon import TelegramClient

logger = logging.getLogger(__name__)


class TelethonExecutor:
    """Run a :class:`ParserJob` against a live Telethon client."""

    async def run(
        self, job: ParserJob, account: Account, *, client: TelegramClient
    ) -> list[ExecutorResult]:
        kind = job.kind
        if kind == ParserKind.USERS_IN_CHAT:
            return await self._users_in_chat(client, job)
        if kind == ParserKind.CHANNELS_OF_USER:
            return await self._channels_of_user(client, job)
        if kind == ParserKind.CHAT_HISTORY:
            return await self._chat_history(client, job)
        if kind == ParserKind.USERS_BY_MESSAGE:
            return await self._users_by_message(client, job)
        return []

    # ------------------------------------------------------------------
    # Kind implementations
    # ------------------------------------------------------------------

    async def _users_in_chat(self, client: Any, job: ParserJob) -> list[ExecutorResult]:
        results: list[ExecutorResult] = []
        async for user in client.iter_participants(job.target):
            results.append(
                ExecutorResult(
                    kind=ParserResultKind.USER,
                    tg_id=getattr(user, "id", None),
                    username=getattr(user, "username", None),
                    title=_user_display_name(user),
                    extra={"chat": job.target},
                )
            )
        return results

    async def _channels_of_user(self, client: Any, job: ParserJob) -> list[ExecutorResult]:
        results: list[ExecutorResult] = []
        async for dialog in client.iter_dialogs():
            if not getattr(dialog, "is_channel", False):
                continue
            entity = getattr(dialog, "entity", dialog)
            results.append(
                ExecutorResult(
                    kind=ParserResultKind.CHANNEL,
                    tg_id=getattr(entity, "id", None),
                    username=getattr(entity, "username", None),
                    title=getattr(entity, "title", None),
                    extra={"user": job.target},
                )
            )
        return results

    async def _chat_history(self, client: Any, job: ParserJob) -> list[ExecutorResult]:
        limit = int(job.params.get("limit", 100)) if job.params else 100
        results: list[ExecutorResult] = []
        async for msg in client.iter_messages(job.target, limit=limit):
            text = getattr(msg, "text", None) or ""
            snippet = text[:255] if text else ""
            results.append(
                ExecutorResult(
                    kind=ParserResultKind.MESSAGE,
                    tg_id=getattr(msg, "id", None),
                    username=None,
                    title=snippet,
                    extra={"peer": job.target, "sender_id": getattr(msg, "sender_id", None)},
                )
            )
        return results

    async def _users_by_message(self, client: Any, job: ParserJob) -> list[ExecutorResult]:
        limit = int(job.params.get("limit", 100)) if job.params else 100
        results: list[ExecutorResult] = []
        seen_ids: set[int] = set()
        async for msg in client.iter_messages(
            job.target, search=job.params.get("query", ""), limit=limit
        ):
            sender_id = getattr(msg, "sender_id", None)
            if sender_id is None or sender_id in seen_ids:
                continue
            seen_ids.add(sender_id)
            sender = getattr(msg, "sender", None)
            results.append(
                ExecutorResult(
                    kind=ParserResultKind.USER,
                    tg_id=sender_id,
                    username=getattr(sender, "username", None) if sender else None,
                    title=_user_display_name(sender) if sender else None,
                    extra={"query": job.params.get("query", ""), "peer": job.target},
                )
            )
        return results


def _user_display_name(user: Any) -> str | None:
    if user is None:
        return None
    first = getattr(user, "first_name", None) or ""
    last = getattr(user, "last_name", None) or ""
    full = f"{first} {last}".strip()
    return full or getattr(user, "username", None)


__all__ = ["TelethonExecutor"]

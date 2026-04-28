"""Parser executor — runs the actual Telethon work.

The combine intentionally separates *intent* (REST submits a
:class:`ParserJob`) from *execution* (a worker process calls Telethon
on behalf of an account). Sprint 3 ships only the bookkeeping side and a
deterministic in-process fake used by tests; the real Telethon-backed
executor will plug in later (Sprint 7) by implementing
:class:`ParserExecutor`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from sonya.db.models_combine import (
    Account,
    ParserJob,
    ParserKind,
    ParserResultKind,
)


@dataclass(frozen=True)
class ExecutorResult:
    """One entity the executor wants to record on the job."""

    kind: ParserResultKind
    tg_id: int | None = None
    username: str | None = None
    title: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


class ParserExecutor(Protocol):
    """Run a :class:`ParserJob` and yield :class:`ExecutorResult` rows.

    Implementations must:

    * be ``async``;
    * tolerate cancellation between yields;
    * NOT mutate the job/account directly — the caller writes the
      results into the DB and updates the job state.
    """

    async def run(
        self, job: ParserJob, account: Account
    ) -> Iterable[ExecutorResult]:  # pragma: no cover - interface
        ...


class StubParserExecutor:
    """Deterministic, offline executor used in tests / smoke runs.

    Produces a small, predictable batch of fake entities for each parser
    kind. The shape of the output matches what the real Telethon-backed
    executor will eventually emit, so downstream code can already be
    wired up against it.
    """

    def __init__(self, *, batch_size: int = 5) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._batch_size = batch_size

    async def run(self, job: ParserJob, account: Account) -> list[ExecutorResult]:
        del account  # the stub doesn't actually talk to Telegram
        return list(self._emit(job))

    def _emit(self, job: ParserJob) -> Iterable[ExecutorResult]:
        n = int(job.params.get("limit") or self._batch_size) if job.params else self._batch_size
        n = max(1, min(n, 100))

        if job.kind == ParserKind.USERS_IN_CHAT:
            for i in range(n):
                yield ExecutorResult(
                    kind=ParserResultKind.USER,
                    tg_id=1_000_000 + i,
                    username=f"member_{i}",
                    title=f"Member {i}",
                    extra={"chat": job.target},
                )
        elif job.kind == ParserKind.CHANNELS_OF_USER:
            for i in range(n):
                yield ExecutorResult(
                    kind=ParserResultKind.CHANNEL,
                    tg_id=2_000_000 + i,
                    username=f"channel_{i}",
                    title=f"Channel {i}",
                    extra={"user": job.target},
                )
        elif job.kind == ParserKind.CHAT_HISTORY:
            for i in range(n):
                yield ExecutorResult(
                    kind=ParserResultKind.MESSAGE,
                    tg_id=3_000_000 + i,
                    username=None,
                    title=f"snippet {i} from {job.target}",
                    extra={"peer": job.target, "offset": i},
                )
        elif job.kind == ParserKind.USERS_BY_MESSAGE:
            for i in range(n):
                yield ExecutorResult(
                    kind=ParserResultKind.USER,
                    tg_id=4_000_000 + i,
                    username=f"poster_{i}",
                    title=f"Poster {i} matched {job.target!r}",
                    extra={"query": job.target, "match_index": i},
                )
        # else: unknown kind — emit nothing (forward-compat).


__all__ = ["ExecutorResult", "ParserExecutor", "StubParserExecutor"]

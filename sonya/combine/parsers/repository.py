"""Async DB CRUD helpers for combine parser jobs and results."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sonya.combine.accounts.repository import DEFAULT_OWNER_ID
from sonya.combine.parsers.executor import ExecutorResult
from sonya.db.models_combine import (
    ParserJob,
    ParserJobStatus,
    ParserResult,
)


async def list_jobs(session: AsyncSession, *, owner_id: int = DEFAULT_OWNER_ID) -> list[ParserJob]:
    res = await session.execute(
        select(ParserJob).where(ParserJob.owner_id == owner_id).order_by(ParserJob.id.desc())
    )
    return list(res.scalars().all())


async def get_job(
    session: AsyncSession, job_id: int, *, owner_id: int = DEFAULT_OWNER_ID
) -> ParserJob | None:
    res = await session.execute(
        select(ParserJob)
        .where(ParserJob.id == job_id, ParserJob.owner_id == owner_id)
        .options(selectinload(ParserJob.results))
    )
    return res.scalar_one_or_none()


async def delete_job(session: AsyncSession, job: ParserJob) -> None:
    await session.delete(job)
    await session.flush()


async def list_results(
    session: AsyncSession,
    job_id: int,
    *,
    offset: int = 0,
    limit: int = 100,
) -> tuple[list[ParserResult], int]:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be in [1..1000]")
    rows_q = (
        select(ParserResult)
        .where(ParserResult.job_id == job_id)
        .order_by(ParserResult.id.asc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await session.execute(rows_q)).scalars().all())
    total = (
        await session.execute(
            select(func.count(ParserResult.id)).where(ParserResult.job_id == job_id)
        )
    ).scalar_one()
    return rows, int(total)


async def append_results(
    session: AsyncSession,
    job: ParserJob,
    results: Iterable[ExecutorResult | ParserResult],
) -> int:
    """Insert results, bump ``job.result_count``, return the number added."""

    rows: list[ParserResult] = []
    for r in results:
        if isinstance(r, ParserResult):
            rows.append(r)
            continue
        rows.append(
            ParserResult(
                job_id=job.id,
                kind=r.kind,
                tg_id=r.tg_id,
                username=r.username,
                title=r.title,
                extra=dict(r.extra) if r.extra else {},
            )
        )
    if not rows:
        return 0
    session.add_all(rows)
    job.result_count += len(rows)
    await session.flush()
    return len(rows)


def mark_running(job: ParserJob) -> None:
    if job.status == ParserJobStatus.PENDING:
        job.status = ParserJobStatus.RUNNING
    if job.started_at is None:
        job.started_at = datetime.now(timezone.utc)


def mark_completed(job: ParserJob, *, success: bool, error: str | None = None) -> None:
    job.status = ParserJobStatus.COMPLETED if success else ParserJobStatus.FAILED
    job.error = error if not success else None
    if job.completed_at is None:
        job.completed_at = datetime.now(timezone.utc)


def mark_cancelled(job: ParserJob) -> None:
    job.status = ParserJobStatus.CANCELLED
    if job.completed_at is None:
        job.completed_at = datetime.now(timezone.utc)


__all__ = [
    "append_results",
    "delete_job",
    "get_job",
    "list_jobs",
    "list_results",
    "mark_cancelled",
    "mark_completed",
    "mark_running",
]

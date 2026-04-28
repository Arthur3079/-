"""Async DB CRUD helpers for combine warming jobs and actions."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sonya.combine.accounts.repository import DEFAULT_OWNER_ID
from sonya.db.models_combine import (
    WarmingAction,
    WarmingActionStatus,
    WarmingJob,
    WarmingJobStatus,
)


async def list_jobs(session: AsyncSession, *, owner_id: int = DEFAULT_OWNER_ID) -> list[WarmingJob]:
    res = await session.execute(
        select(WarmingJob)
        .where(WarmingJob.owner_id == owner_id)
        .options(selectinload(WarmingJob.actions))
        .order_by(WarmingJob.id.desc())
    )
    return list(res.scalars().unique())


async def get_job(
    session: AsyncSession, job_id: int, *, owner_id: int = DEFAULT_OWNER_ID
) -> WarmingJob | None:
    res = await session.execute(
        select(WarmingJob)
        .where(WarmingJob.id == job_id, WarmingJob.owner_id == owner_id)
        .options(selectinload(WarmingJob.actions), selectinload(WarmingJob.account))
    )
    return res.scalar_one_or_none()


async def get_job_with_account(
    session: AsyncSession, job_id: int, *, owner_id: int = DEFAULT_OWNER_ID
) -> WarmingJob | None:
    """Same as ``get_job`` but with the parent ``Account`` eagerly loaded.

    Required by :class:`TrustScoreUpdater.complete_action` because it
    mutates ``job.account.trust_score`` synchronously.
    """
    return await get_job(session, job_id, owner_id=owner_id)


async def get_action(
    session: AsyncSession, action_id: int, *, job_id: int | None = None
) -> WarmingAction | None:
    action = await session.get(WarmingAction, action_id)
    if action is None:
        return None
    if job_id is not None and action.job_id != job_id:
        return None
    return action


async def delete_job(session: AsyncSession, job: WarmingJob) -> None:
    await session.delete(job)
    await session.flush()


def summarize(job: WarmingJob) -> tuple[int, int, int, int]:
    """Return (total, done, failed, pending) counts for a job's actions."""
    total = len(job.actions)
    done = sum(1 for a in job.actions if a.status == WarmingActionStatus.DONE)
    failed = sum(1 for a in job.actions if a.status == WarmingActionStatus.FAILED)
    pending = sum(1 for a in job.actions if a.status == WarmingActionStatus.PENDING)
    return total, done, failed, pending


async def cancel_pending_actions(session: AsyncSession, job: WarmingJob) -> int:
    """Mark every still-pending action as ``skipped``. Returns # changed."""
    n = 0
    for a in job.actions:
        if a.status == WarmingActionStatus.PENDING:
            a.status = WarmingActionStatus.SKIPPED
            n += 1
    if n:
        job.status = WarmingJobStatus.CANCELLED
        await session.flush()
    return n


__all__ = [
    "cancel_pending_actions",
    "delete_job",
    "get_action",
    "get_job",
    "get_job_with_account",
    "list_jobs",
    "summarize",
]

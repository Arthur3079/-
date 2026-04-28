"""Unit tests for `sonya.combine.warming.trust.TrustScoreUpdater`."""

from __future__ import annotations

import random
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sonya.combine.warming.planner import PlanConfig, WarmingPlanner
from sonya.combine.warming.trust import TRUST_SCORE_MAX, TrustScoreUpdater
from sonya.db.base import Base
from sonya.db.models_combine import (
    Account,
    AccountRole,
    AccountStatus,
    Owner,
    WarmingActionStatus,
    WarmingJob,
    WarmingJobStatus,
)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _make_job(session: AsyncSession, *, n_actions: int = 3) -> WarmingJob:
    owner = Owner(id=1, name="default")
    session.add(owner)
    await session.flush()
    acc = Account(
        owner_id=1,
        phone="+10000000050",
        role=AccountRole.MULTI,
        status=AccountStatus.NEW,
        trust_score=0,
    )
    session.add(acc)
    await session.flush()

    config = PlanConfig(
        duration_days=2,
        actions_per_day_min=n_actions,
        actions_per_day_max=n_actions,
    )
    planner = WarmingPlanner(rng=random.Random(0))
    actions = planner.build(acc, config=config)
    job = WarmingJob(
        owner_id=1,
        account_id=acc.id,
        status=WarmingJobStatus.PENDING,
        target_trust_score=10,
        actions=actions,
        account=acc,
    )
    session.add(job)
    await session.flush()
    return job


@pytest.mark.asyncio
async def test_apply_clamps_to_zero_and_max(session: AsyncSession) -> None:
    job = await _make_job(session)
    upd = TrustScoreUpdater()

    new = await upd.apply(session, job.account, 9999)
    assert new == TRUST_SCORE_MAX
    new = await upd.apply(session, job.account, -5000)
    assert new == 0


@pytest.mark.asyncio
async def test_complete_action_success_bumps_trust_and_advances_status(
    session: AsyncSession,
) -> None:
    job = await _make_job(session, n_actions=2)
    action = job.actions[0]
    upd = TrustScoreUpdater()

    await upd.complete_action(session, job=job, action=action, success=True)

    assert action.status == WarmingActionStatus.DONE
    assert action.error is None
    assert isinstance(action.executed_at, datetime)
    assert job.status == WarmingJobStatus.RUNNING
    assert job.last_action_at is not None
    # Account moves NEW -> WARMING after the first successful action.
    assert job.account.status == AccountStatus.WARMING
    assert job.account.trust_score == action.trust_delta


@pytest.mark.asyncio
async def test_complete_action_failure_does_not_bump_trust(session: AsyncSession) -> None:
    job = await _make_job(session)
    action = job.actions[0]
    upd = TrustScoreUpdater()

    initial = job.account.trust_score
    await upd.complete_action(session, job=job, action=action, success=False, error="boom")
    assert action.status == WarmingActionStatus.FAILED
    assert action.error == "boom"
    assert job.account.trust_score == initial


@pytest.mark.asyncio
async def test_completing_all_actions_marks_job_completed(session: AsyncSession) -> None:
    job = await _make_job(session, n_actions=3)
    upd = TrustScoreUpdater()

    for action in list(job.actions):
        await upd.complete_action(session, job=job, action=action, success=True)

    assert job.status == WarmingJobStatus.COMPLETED
    assert job.completed_at is not None
    # If trust_score met or exceeded target, status should advance to ACTIVE.
    if job.account.trust_score >= job.target_trust_score:
        assert job.account.status == AccountStatus.ACTIVE


@pytest.mark.asyncio
async def test_skipped_actions_count_toward_completion(session: AsyncSession) -> None:
    job = await _make_job(session, n_actions=1)  # 1/day × 2 days = 2 actions
    assert len(job.actions) == 2
    upd = TrustScoreUpdater()

    # Mark the second one skipped first (operator cancelled it).
    job.actions[1].status = WarmingActionStatus.SKIPPED
    job.actions[1].executed_at = datetime.now(timezone.utc)

    # Then complete the remaining pending action — that should flip the job
    # to COMPLETED because every action is now in a terminal state.
    await upd.complete_action(session, job=job, action=job.actions[0], success=True)
    assert job.status == WarmingJobStatus.COMPLETED
    assert job.completed_at is not None

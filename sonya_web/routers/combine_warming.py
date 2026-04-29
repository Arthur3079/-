"""REST router for combine warming — jobs CRUD + lifecycle controls.

Mounted at ``/api/combine/warming``.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.combine.accounts import repository as account_repo
from sonya.combine.warming import repository as repo
from sonya.combine.warming.planner import DEFAULT_PLAN_CONFIG, PlanConfig, WarmingPlanner
from sonya.combine.warming.schemas import (
    WarmingActionCompleteIn,
    WarmingActionOut,
    WarmingJobCreateIn,
    WarmingJobDetailOut,
    WarmingJobOut,
    WarmingPlanConfigIn,
)
from sonya.combine.warming.trust import TrustScoreUpdater
from sonya.db.models_combine import (
    WarmingAction,
    WarmingActionStatus,
    WarmingJob,
    WarmingJobStatus,
)
from sonya_web.auth_deps import ensure_request_owner, get_current_owner_id
from sonya_web.deps import get_session

router = APIRouter(prefix="/combine/warming", tags=["combine"])


def _to_out(job: WarmingJob) -> WarmingJobOut:
    total, done, failed, pending = repo.summarize(job)
    return WarmingJobOut(
        id=job.id,
        owner_id=job.owner_id,
        account_id=job.account_id,
        status=job.status,
        target_trust_score=job.target_trust_score,
        started_at=job.started_at,
        completed_at=job.completed_at,
        last_action_at=job.last_action_at,
        note=job.note,
        total_actions=total,
        actions_done=done,
        actions_failed=failed,
        actions_pending=pending,
    )


def _to_detail(job: WarmingJob) -> WarmingJobDetailOut:
    base = _to_out(job)
    return WarmingJobDetailOut(
        **base.model_dump(),
        actions=[WarmingActionOut.model_validate(a) for a in job.actions],
    )


def _resolve_config(override: WarmingPlanConfigIn | None) -> PlanConfig:
    if override is None:
        return DEFAULT_PLAN_CONFIG
    base = DEFAULT_PLAN_CONFIG
    return PlanConfig(
        duration_days=override.duration_days or base.duration_days,
        actions_per_day_min=override.actions_per_day_min or base.actions_per_day_min,
        actions_per_day_max=override.actions_per_day_max or base.actions_per_day_max,
        target_trust_score=override.target_trust_score or base.target_trust_score,
        channels=tuple(override.channels) if override.channels is not None else base.channels,
        reaction_targets=(
            tuple(override.reaction_targets)
            if override.reaction_targets is not None
            else base.reaction_targets
        ),
        idle_chat_targets=(
            tuple(override.idle_chat_targets)
            if override.idle_chat_targets is not None
            else base.idle_chat_targets
        ),
    )


@router.get("/jobs", response_model=list[WarmingJobOut])
async def list_jobs(
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> list[WarmingJobOut]:
    jobs = await repo.list_jobs(session, owner_id=owner_id)
    return [_to_out(j) for j in jobs]


@router.post("/jobs", response_model=WarmingJobDetailOut, status_code=201)
async def create_job(
    payload: WarmingJobCreateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
    _owner: Annotated[object, Depends(ensure_request_owner)],
) -> WarmingJobDetailOut:
    account = await account_repo.get_account(session, payload.account_id, owner_id=owner_id)
    if account is None:
        raise HTTPException(status_code=400, detail="account does not exist")

    config = _resolve_config(payload.plan)
    planner = WarmingPlanner(rng=random.Random(payload.seed) if payload.seed is not None else None)
    actions = planner.build(account, config=config)

    job = WarmingJob(
        owner_id=account.owner_id,
        account_id=account.id,
        status=WarmingJobStatus.PENDING,
        target_trust_score=config.target_trust_score,
        note=payload.note,
        actions=actions,
    )
    session.add(job)
    await session.flush()
    await session.commit()

    fresh = await repo.get_job(session, job.id, owner_id=owner_id)
    assert fresh is not None
    return _to_detail(fresh)


@router.get("/jobs/{job_id}", response_model=WarmingJobDetailOut)
async def get_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> WarmingJobDetailOut:
    job = await repo.get_job(session, job_id, owner_id=owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="warming job not found")
    return _to_detail(job)


@router.post("/jobs/{job_id}/pause", response_model=WarmingJobOut)
async def pause_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> WarmingJobOut:
    job = await repo.get_job(session, job_id, owner_id=owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="warming job not found")
    if job.status in {WarmingJobStatus.COMPLETED, WarmingJobStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail=f"job already {job.status.value}")
    job.status = WarmingJobStatus.PAUSED
    await session.commit()
    return _to_out(job)


@router.post("/jobs/{job_id}/resume", response_model=WarmingJobOut)
async def resume_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> WarmingJobOut:
    job = await repo.get_job(session, job_id, owner_id=owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="warming job not found")
    if job.status != WarmingJobStatus.PAUSED:
        raise HTTPException(status_code=409, detail=f"job is {job.status.value}, not paused")
    has_executed = any(a.status != WarmingActionStatus.PENDING for a in job.actions)
    job.status = WarmingJobStatus.RUNNING if has_executed else WarmingJobStatus.PENDING
    await session.commit()
    return _to_out(job)


@router.post("/jobs/{job_id}/cancel", response_model=WarmingJobOut)
async def cancel_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> WarmingJobOut:
    job = await repo.get_job(session, job_id, owner_id=owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="warming job not found")
    if job.status in {WarmingJobStatus.COMPLETED, WarmingJobStatus.CANCELLED}:
        return _to_out(job)
    await repo.cancel_pending_actions(session, job)
    if job.completed_at is None:
        job.completed_at = datetime.now(timezone.utc)
    await session.commit()
    return _to_out(job)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> None:
    job = await repo.get_job(session, job_id, owner_id=owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="warming job not found")
    await repo.delete_job(session, job)
    await session.commit()


@router.post(
    "/jobs/{job_id}/actions/{action_id}/complete",
    response_model=WarmingActionOut,
)
async def complete_action(
    job_id: int,
    action_id: int,
    payload: WarmingActionCompleteIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> WarmingActionOut:
    job = await repo.get_job(session, job_id, owner_id=owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="warming job not found")
    action: WarmingAction | None = next((a for a in job.actions if a.id == action_id), None)
    if action is None:
        raise HTTPException(status_code=404, detail="action not found in this job")
    if action.status != WarmingActionStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"action already {action.status.value}")

    if job.status in {WarmingJobStatus.PAUSED, WarmingJobStatus.CANCELLED}:
        raise HTTPException(
            status_code=409, detail=f"cannot complete actions while job is {job.status.value}"
        )

    updater = TrustScoreUpdater()
    await updater.complete_action(
        session,
        job=job,
        action=action,
        success=payload.success,
        error=payload.error,
    )
    await session.commit()
    return WarmingActionOut.model_validate(action)


__all__ = ["router"]

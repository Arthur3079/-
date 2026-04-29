"""REST router for combine parser jobs.

Mounted at ``/api/combine/parsers``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.combine.accounts import repository as account_repo
from sonya.combine.parsers import repository as repo
from sonya.combine.parsers.executor import StubParserExecutor
from sonya.combine.parsers.schemas import (
    ParserJobCompleteIn,
    ParserJobCreateIn,
    ParserJobOut,
    ParserResultOut,
    ParserResultsBatchIn,
    ParserResultsPage,
    ParserRunStubIn,
)
from sonya.db.models_combine import (
    ParserJob,
    ParserJobStatus,
)
from sonya_web.auth_deps import ensure_request_owner, get_current_owner_id
from sonya_web.deps import get_session

router = APIRouter(prefix="/combine/parsers", tags=["combine"])


@router.get("/jobs", response_model=list[ParserJobOut])
async def list_jobs(
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> list[ParserJob]:
    return await repo.list_jobs(session, owner_id=owner_id)


@router.post("/jobs", response_model=ParserJobOut, status_code=201)
async def create_job(
    payload: ParserJobCreateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
    _owner: Annotated[object, Depends(ensure_request_owner)],
) -> ParserJob:
    account = await account_repo.get_account(session, payload.account_id, owner_id=owner_id)
    if account is None:
        raise HTTPException(status_code=400, detail="account does not exist")

    job = ParserJob(
        owner_id=account.owner_id,
        account_id=account.id,
        kind=payload.kind,
        target=payload.target,
        params=dict(payload.params),
        status=ParserJobStatus.PENDING,
        note=payload.note,
    )
    session.add(job)
    await session.flush()
    await session.commit()
    return job


@router.get("/jobs/{job_id}", response_model=ParserJobOut)
async def get_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> ParserJob:
    job = await repo.get_job(session, job_id, owner_id=owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="parser job not found")
    return job


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> None:
    job = await repo.get_job(session, job_id, owner_id=owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="parser job not found")
    await repo.delete_job(session, job)
    await session.commit()


@router.post("/jobs/{job_id}/cancel", response_model=ParserJobOut)
async def cancel_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> ParserJob:
    job = await repo.get_job(session, job_id, owner_id=owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="parser job not found")
    if job.status in {ParserJobStatus.COMPLETED, ParserJobStatus.CANCELLED}:
        return job
    repo.mark_cancelled(job)
    await session.commit()
    return job


@router.post("/jobs/{job_id}/complete", response_model=ParserJobOut)
async def complete_job(
    job_id: int,
    payload: ParserJobCompleteIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> ParserJob:
    job = await repo.get_job(session, job_id, owner_id=owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="parser job not found")
    if job.status in {ParserJobStatus.COMPLETED, ParserJobStatus.CANCELLED, ParserJobStatus.FAILED}:
        raise HTTPException(status_code=409, detail=f"job already {job.status.value}")
    repo.mark_completed(job, success=payload.success, error=payload.error)
    await session.commit()
    return job


@router.get("/jobs/{job_id}/results", response_model=ParserResultsPage)
async def list_results(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> ParserResultsPage:
    job = await repo.get_job(session, job_id, owner_id=owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="parser job not found")
    rows, total = await repo.list_results(session, job_id, offset=offset, limit=limit)
    return ParserResultsPage(
        items=[ParserResultOut.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/jobs/{job_id}/results", response_model=ParserJobOut)
async def push_results(
    job_id: int,
    payload: ParserResultsBatchIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> ParserJob:
    """Append a batch of results — used by the executor / smoke runs."""
    job = await repo.get_job(session, job_id, owner_id=owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="parser job not found")
    if job.status in {ParserJobStatus.COMPLETED, ParserJobStatus.CANCELLED, ParserJobStatus.FAILED}:
        raise HTTPException(
            status_code=409, detail=f"job is {job.status.value}, cannot accept results"
        )
    repo.mark_running(job)
    await repo.append_results(session, job, payload.results)
    await session.commit()
    return job


@router.post("/jobs/{job_id}/run-stub", response_model=ParserJobOut)
async def run_stub(
    job_id: int,
    payload: ParserRunStubIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> ParserJob:
    """Run the deterministic stub executor and store its output.

    Provided for dev/QA — lets the operator end-to-end exercise the
    parser pipeline without a logged-in Telegram account.
    """
    job = await repo.get_job(session, job_id, owner_id=owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="parser job not found")
    if job.status in {ParserJobStatus.COMPLETED, ParserJobStatus.CANCELLED, ParserJobStatus.FAILED}:
        raise HTTPException(status_code=409, detail=f"job already {job.status.value}")

    account = await account_repo.get_account(session, job.account_id, owner_id=owner_id)
    if account is None:
        raise HTTPException(status_code=400, detail="account no longer exists")

    repo.mark_running(job)
    executor = StubParserExecutor(batch_size=payload.batch_size or 5)
    results = await executor.run(job, account)
    await repo.append_results(session, job, results)
    repo.mark_completed(job, success=True)
    await session.commit()
    return job


__all__ = ["router"]

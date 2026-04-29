"""REST router for combine analytics (module 8 — Sprint 6).

Mounted at ``/api/combine/analytics``. Six read-only endpoints that wrap
:class:`sonya.combine.analytics.aggregator.AnalyticsAggregator`.

The endpoints are idempotent and parameter-free on purpose; time-series
filtering would mean a new daily-rollup table and is left for a future
sprint.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.combine.analytics import AnalyticsAggregator
from sonya.combine.analytics.schemas import (
    AccountsSummary,
    CommentingSummary,
    OverallSummary,
    ParsersSummary,
    ReactionsSummary,
    WarmingSummary,
)
from sonya_web.auth_deps import get_current_owner_id
from sonya_web.deps import get_session

router = APIRouter(prefix="/combine/analytics", tags=["combine"])


@router.get("/summary", response_model=OverallSummary)
async def get_overall_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> OverallSummary:
    return await AnalyticsAggregator(session, owner_id=owner_id).overall_summary()


@router.get("/accounts", response_model=AccountsSummary)
async def get_accounts_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> AccountsSummary:
    return await AnalyticsAggregator(session, owner_id=owner_id).accounts_summary()


@router.get("/warming", response_model=WarmingSummary)
async def get_warming_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> WarmingSummary:
    return await AnalyticsAggregator(session, owner_id=owner_id).warming_summary()


@router.get("/parsers", response_model=ParsersSummary)
async def get_parsers_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> ParsersSummary:
    return await AnalyticsAggregator(session, owner_id=owner_id).parsers_summary()


@router.get("/commenting", response_model=CommentingSummary)
async def get_commenting_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> CommentingSummary:
    return await AnalyticsAggregator(session, owner_id=owner_id).commenting_summary()


@router.get("/reactions", response_model=ReactionsSummary)
async def get_reactions_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[int, Depends(get_current_owner_id)],
) -> ReactionsSummary:
    return await AnalyticsAggregator(session, owner_id=owner_id).reactions_summary()

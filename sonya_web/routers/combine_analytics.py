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
from sonya_web.deps import get_session

router = APIRouter(prefix="/combine/analytics", tags=["combine"])


@router.get("/summary", response_model=OverallSummary)
async def get_overall_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OverallSummary:
    return await AnalyticsAggregator(session).overall_summary()


@router.get("/accounts", response_model=AccountsSummary)
async def get_accounts_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AccountsSummary:
    return await AnalyticsAggregator(session).accounts_summary()


@router.get("/warming", response_model=WarmingSummary)
async def get_warming_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WarmingSummary:
    return await AnalyticsAggregator(session).warming_summary()


@router.get("/parsers", response_model=ParsersSummary)
async def get_parsers_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ParsersSummary:
    return await AnalyticsAggregator(session).parsers_summary()


@router.get("/commenting", response_model=CommentingSummary)
async def get_commenting_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CommentingSummary:
    return await AnalyticsAggregator(session).commenting_summary()


@router.get("/reactions", response_model=ReactionsSummary)
async def get_reactions_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReactionsSummary:
    return await AnalyticsAggregator(session).reactions_summary()

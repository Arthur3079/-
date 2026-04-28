"""Async DB CRUD helpers for combine commenting campaigns / posts / comments."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sonya.combine.accounts.repository import DEFAULT_OWNER_ID
from sonya.db.models_combine import (
    Comment,
    CommentingCampaign,
    CommentingCampaignStatus,
    ObservedPost,
)


async def list_campaigns(
    session: AsyncSession, *, owner_id: int = DEFAULT_OWNER_ID
) -> list[CommentingCampaign]:
    res = await session.execute(
        select(CommentingCampaign)
        .where(CommentingCampaign.owner_id == owner_id)
        .order_by(CommentingCampaign.id.desc())
    )
    return list(res.scalars().all())


async def get_campaign(
    session: AsyncSession,
    campaign_id: int,
    *,
    owner_id: int = DEFAULT_OWNER_ID,
) -> CommentingCampaign | None:
    res = await session.execute(
        select(CommentingCampaign)
        .where(
            CommentingCampaign.id == campaign_id,
            CommentingCampaign.owner_id == owner_id,
        )
        .options(selectinload(CommentingCampaign.posts))
    )
    return res.scalar_one_or_none()


async def delete_campaign(session: AsyncSession, campaign: CommentingCampaign) -> None:
    await session.delete(campaign)
    await session.flush()


async def list_posts(
    session: AsyncSession, campaign_id: int, *, limit: int = 100, offset: int = 0
) -> list[ObservedPost]:
    res = await session.execute(
        select(ObservedPost)
        .where(ObservedPost.campaign_id == campaign_id)
        .order_by(ObservedPost.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(res.scalars().all())


async def get_post_for_campaign(
    session: AsyncSession, campaign_id: int, post_id: int
) -> ObservedPost | None:
    res = await session.execute(
        select(ObservedPost)
        .where(
            ObservedPost.id == post_id,
            ObservedPost.campaign_id == campaign_id,
        )
        .options(selectinload(ObservedPost.comments))
    )
    return res.scalar_one_or_none()


async def get_post_by_message_id(
    session: AsyncSession, campaign_id: int, channel: str, tg_message_id: int
) -> ObservedPost | None:
    res = await session.execute(
        select(ObservedPost).where(
            ObservedPost.campaign_id == campaign_id,
            ObservedPost.channel == channel,
            ObservedPost.tg_message_id == tg_message_id,
        )
    )
    return res.scalar_one_or_none()


async def list_comments(session: AsyncSession, post_id: int) -> list[Comment]:
    res = await session.execute(
        select(Comment).where(Comment.post_id == post_id).order_by(Comment.id.asc())
    )
    return list(res.scalars().all())


def transition_to_status(campaign: CommentingCampaign, status: CommentingCampaignStatus) -> None:
    """Move the campaign into a new status with timestamp bookkeeping."""

    now = datetime.now(timezone.utc)
    campaign.status = status
    if status == CommentingCampaignStatus.RUNNING and campaign.started_at is None:
        campaign.started_at = now
    elif status == CommentingCampaignStatus.PAUSED:
        campaign.paused_at = now
    elif status == CommentingCampaignStatus.ARCHIVED:
        campaign.archived_at = now


__all__ = [
    "delete_campaign",
    "get_campaign",
    "get_post_by_message_id",
    "get_post_for_campaign",
    "list_campaigns",
    "list_comments",
    "list_posts",
    "transition_to_status",
]

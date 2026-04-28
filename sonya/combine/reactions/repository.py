"""Async DB CRUD helpers for combine reaction campaigns / targets / reactions."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sonya.combine.accounts.repository import DEFAULT_OWNER_ID
from sonya.db.models_combine import (
    Reaction,
    ReactionCampaign,
    ReactionCampaignStatus,
    ReactionTarget,
)


async def list_campaigns(
    session: AsyncSession, *, owner_id: int = DEFAULT_OWNER_ID
) -> list[ReactionCampaign]:
    res = await session.execute(
        select(ReactionCampaign)
        .where(ReactionCampaign.owner_id == owner_id)
        .order_by(ReactionCampaign.id.desc())
    )
    return list(res.scalars().all())


async def get_campaign(
    session: AsyncSession,
    campaign_id: int,
    *,
    owner_id: int = DEFAULT_OWNER_ID,
) -> ReactionCampaign | None:
    res = await session.execute(
        select(ReactionCampaign)
        .where(
            ReactionCampaign.id == campaign_id,
            ReactionCampaign.owner_id == owner_id,
        )
        .options(selectinload(ReactionCampaign.targets))
    )
    return res.scalar_one_or_none()


async def delete_campaign(session: AsyncSession, campaign: ReactionCampaign) -> None:
    await session.delete(campaign)
    await session.flush()


async def list_targets(
    session: AsyncSession, campaign_id: int, *, limit: int = 100, offset: int = 0
) -> list[ReactionTarget]:
    res = await session.execute(
        select(ReactionTarget)
        .where(ReactionTarget.campaign_id == campaign_id)
        .order_by(ReactionTarget.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(res.scalars().all())


async def get_target_for_campaign(
    session: AsyncSession, campaign_id: int, target_id: int
) -> ReactionTarget | None:
    res = await session.execute(
        select(ReactionTarget)
        .where(
            ReactionTarget.id == target_id,
            ReactionTarget.campaign_id == campaign_id,
        )
        .options(selectinload(ReactionTarget.reactions))
    )
    return res.scalar_one_or_none()


async def get_target_by_message_id(
    session: AsyncSession, campaign_id: int, channel: str, tg_message_id: int
) -> ReactionTarget | None:
    res = await session.execute(
        select(ReactionTarget).where(
            ReactionTarget.campaign_id == campaign_id,
            ReactionTarget.channel == channel,
            ReactionTarget.tg_message_id == tg_message_id,
        )
    )
    return res.scalar_one_or_none()


async def list_reactions(session: AsyncSession, target_id: int) -> list[Reaction]:
    res = await session.execute(
        select(Reaction).where(Reaction.target_id == target_id).order_by(Reaction.id.asc())
    )
    return list(res.scalars().all())


def transition_to_status(campaign: ReactionCampaign, status: ReactionCampaignStatus) -> None:
    now = datetime.now(timezone.utc)
    campaign.status = status
    if status == ReactionCampaignStatus.RUNNING and campaign.started_at is None:
        campaign.started_at = now
    elif status == ReactionCampaignStatus.PAUSED:
        campaign.paused_at = now
    elif status == ReactionCampaignStatus.ARCHIVED:
        campaign.archived_at = now


__all__ = [
    "delete_campaign",
    "get_campaign",
    "get_target_by_message_id",
    "get_target_for_campaign",
    "list_campaigns",
    "list_reactions",
    "list_targets",
    "transition_to_status",
]

"""REST router for combine mass-reactions (module 6).

Mounted at ``/api/combine/reactions``. Surface mirrors the commenting
module on purpose — the worker / front-end can treat both as variants
of the same lifecycle (campaign → observed item → per-account work).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.combine.accounts import repository as account_repo
from sonya.combine.reactions import repository as repo
from sonya.combine.reactions.planner import ReactionPlanner
from sonya.combine.reactions.schemas import (
    ReactionCampaignCreateIn,
    ReactionCampaignOut,
    ReactionCampaignUpdateIn,
    ReactionOut,
    ReactionRecordIn,
    ReactionTargetIn,
    ReactionTargetOut,
)
from sonya.db.models_combine import (
    Reaction,
    ReactionCampaign,
    ReactionCampaignStatus,
    ReactionStatus,
    ReactionTarget,
    ReactionTargetStatus,
)
from sonya_web.deps import get_session

router = APIRouter(prefix="/combine/reactions", tags=["combine"])


def _validate_accounts(payload_account_ids: list[int] | None, known_ids: set[int]) -> None:
    if not payload_account_ids:
        return
    unknown = set(payload_account_ids) - known_ids
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown account_ids: {sorted(unknown)}",
        )


@router.get("/campaigns", response_model=list[ReactionCampaignOut])
async def list_campaigns(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ReactionCampaign]:
    return await repo.list_campaigns(session)


@router.post("/campaigns", response_model=ReactionCampaignOut, status_code=201)
async def create_campaign(
    payload: ReactionCampaignCreateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReactionCampaign:
    owner = await account_repo.ensure_default_owner(session)
    accounts = await account_repo.list_accounts(session)
    _validate_accounts(payload.account_ids, {a.id for a in accounts})

    campaign = ReactionCampaign(
        owner_id=owner.id,
        name=payload.name,
        target_channels=list(payload.target_channels),
        account_ids=list(payload.account_ids),
        emojis=list(payload.emojis),
        accounts_per_post=payload.accounts_per_post,
        max_reactions_per_day=payload.max_reactions_per_day,
        note=payload.note,
        status=ReactionCampaignStatus.DRAFT,
    )
    session.add(campaign)
    await session.flush()
    await session.commit()
    return campaign


@router.get("/campaigns/{campaign_id}", response_model=ReactionCampaignOut)
async def get_campaign(
    campaign_id: int, session: Annotated[AsyncSession, Depends(get_session)]
) -> ReactionCampaign:
    campaign = await repo.get_campaign(session, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return campaign


@router.patch("/campaigns/{campaign_id}", response_model=ReactionCampaignOut)
async def update_campaign(
    campaign_id: int,
    payload: ReactionCampaignUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReactionCampaign:
    campaign = await repo.get_campaign(session, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")

    if payload.account_ids is not None:
        accounts = await account_repo.list_accounts(session)
        _validate_accounts(payload.account_ids, {a.id for a in accounts})
        campaign.account_ids = list(payload.account_ids)

    if payload.name is not None:
        campaign.name = payload.name
    if payload.target_channels is not None:
        campaign.target_channels = list(payload.target_channels)
    if payload.emojis is not None:
        campaign.emojis = list(payload.emojis)
    if payload.accounts_per_post is not None:
        campaign.accounts_per_post = payload.accounts_per_post
    if payload.max_reactions_per_day is not None:
        campaign.max_reactions_per_day = payload.max_reactions_per_day
    if payload.note is not None:
        campaign.note = payload.note

    await session.commit()
    return campaign


@router.delete("/campaigns/{campaign_id}", status_code=204)
async def delete_campaign(
    campaign_id: int, session: Annotated[AsyncSession, Depends(get_session)]
) -> None:
    campaign = await repo.get_campaign(session, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    await repo.delete_campaign(session, campaign)
    await session.commit()


def _lifecycle(target: ReactionCampaignStatus):
    async def _handler(
        campaign_id: int,
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> ReactionCampaign:
        campaign = await repo.get_campaign(session, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign not found")
        if campaign.status == ReactionCampaignStatus.ARCHIVED:
            raise HTTPException(status_code=409, detail="campaign is archived")
        if target == ReactionCampaignStatus.RUNNING:
            if not campaign.account_ids:
                raise HTTPException(
                    status_code=400,
                    detail="cannot start a campaign without accounts attached",
                )
            if not campaign.emojis:
                raise HTTPException(
                    status_code=400,
                    detail="cannot start a campaign without emojis configured",
                )
        repo.transition_to_status(campaign, target)
        await session.commit()
        return campaign

    return _handler


router.post(
    "/campaigns/{campaign_id}/start",
    response_model=ReactionCampaignOut,
)(_lifecycle(ReactionCampaignStatus.RUNNING))
router.post(
    "/campaigns/{campaign_id}/pause",
    response_model=ReactionCampaignOut,
)(_lifecycle(ReactionCampaignStatus.PAUSED))
router.post(
    "/campaigns/{campaign_id}/archive",
    response_model=ReactionCampaignOut,
)(_lifecycle(ReactionCampaignStatus.ARCHIVED))


# ---------- TARGETS ----------


@router.get(
    "/campaigns/{campaign_id}/targets",
    response_model=list[ReactionTargetOut],
)
async def list_targets(
    campaign_id: int, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[ReactionTarget]:
    campaign = await repo.get_campaign(session, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return await repo.list_targets(session, campaign_id)


@router.post(
    "/campaigns/{campaign_id}/targets",
    response_model=ReactionTargetOut,
    status_code=201,
)
async def push_target(
    campaign_id: int,
    payload: ReactionTargetIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReactionTarget:
    campaign = await repo.get_campaign(session, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    if campaign.status == ReactionCampaignStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="campaign is archived")
    if campaign.target_channels and payload.channel not in campaign.target_channels:
        raise HTTPException(
            status_code=400,
            detail=f"channel {payload.channel!r} is not in campaign target list",
        )

    existing = await repo.get_target_by_message_id(
        session, campaign_id, payload.channel, payload.tg_message_id
    )
    if existing is not None:
        return existing

    target = ReactionTarget(
        campaign_id=campaign_id,
        channel=payload.channel,
        tg_message_id=payload.tg_message_id,
        status=ReactionTargetStatus.PENDING,
        observed_at=datetime.now(timezone.utc),
    )
    session.add(target)
    await session.flush()
    await session.commit()
    return target


@router.post(
    "/campaigns/{campaign_id}/targets/{target_id}/plan",
    response_model=list[ReactionOut],
)
async def plan_target(
    campaign_id: int,
    target_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Reaction]:
    """Run :class:`ReactionPlanner` and persist its output.

    Idempotent: if the target already has reactions, returns them
    unchanged. Otherwise picks `accounts_per_post` accounts from the
    campaign pool, assigns each one an emoji, and inserts pending rows.
    """

    campaign = await repo.get_campaign(session, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    target = await repo.get_target_for_campaign(session, campaign_id, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found in this campaign")
    if target.reactions:
        return list(target.reactions)
    if not campaign.emojis:
        raise HTTPException(status_code=400, detail="campaign has no emojis configured")

    planner = ReactionPlanner()
    plans = planner.plan(campaign=campaign, target=target)
    if not plans:
        raise HTTPException(
            status_code=400, detail="campaign has no accounts to plan reactions for"
        )

    rows = [
        Reaction(
            target_id=target.id,
            account_id=p.account_id,
            emoji=p.emoji,
            status=ReactionStatus.PENDING,
        )
        for p in plans
    ]
    session.add_all(rows)
    target.status = ReactionTargetStatus.PLANNED
    await session.flush()
    await session.commit()
    return rows


@router.get(
    "/campaigns/{campaign_id}/targets/{target_id}/reactions",
    response_model=list[ReactionOut],
)
async def list_reactions(
    campaign_id: int,
    target_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Reaction]:
    target = await repo.get_target_for_campaign(session, campaign_id, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found in this campaign")
    return await repo.list_reactions(session, target.id)


@router.post(
    "/campaigns/{campaign_id}/targets/{target_id}/reactions/{reaction_id}/record",
    response_model=ReactionOut,
)
async def record_reaction_outcome(
    campaign_id: int,
    target_id: int,
    reaction_id: int,
    payload: ReactionRecordIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Reaction:
    target = await repo.get_target_for_campaign(session, campaign_id, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found in this campaign")

    reaction = next((r for r in target.reactions if r.id == reaction_id), None)
    if reaction is None:
        raise HTTPException(status_code=404, detail="reaction not found")
    if reaction.status in {
        ReactionStatus.POSTED,
        ReactionStatus.FAILED,
        ReactionStatus.SKIPPED,
    }:
        raise HTTPException(status_code=409, detail=f"reaction already {reaction.status.value}")

    now = datetime.now(timezone.utc)
    if payload.success:
        reaction.status = ReactionStatus.POSTED
        reaction.posted_at = now
        reaction.error = None
    else:
        reaction.status = ReactionStatus.FAILED
        reaction.error = payload.error
        reaction.posted_at = now

    # Advance the target to `done` once every reaction has reached a
    # terminal state. Fresh-fetch the reactions list so we see the row we
    # just mutated.
    rows = await repo.list_reactions(session, target.id)
    if all(
        r.status in {ReactionStatus.POSTED, ReactionStatus.FAILED, ReactionStatus.SKIPPED}
        for r in rows
    ):
        target.status = ReactionTargetStatus.DONE

    await session.commit()
    return reaction


__all__ = ["router"]

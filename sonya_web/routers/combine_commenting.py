"""REST router for combine neuro-commenting (module 3).

Mounted at ``/api/combine/commenting``. Surface:

* ``/campaigns``                — CRUD on campaigns + lifecycle controls.
* ``/campaigns/{id}/posts``     — list / push observed posts.
* ``/campaigns/{id}/posts/{pid}/render-stub``  — generate a comment offline.
* ``/campaigns/{id}/posts/{pid}/comments``     — list / record a comment.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.combine.accounts import repository as account_repo
from sonya.combine.commenting import repository as repo
from sonya.combine.commenting.renderer import StubCommentRenderer
from sonya.combine.commenting.schemas import (
    CampaignCreateIn,
    CampaignOut,
    CampaignUpdateIn,
    CommentOut,
    CommentRecordIn,
    ObservedPostIn,
    ObservedPostOut,
    RenderStubIn,
)
from sonya.db.models_combine import (
    Comment,
    CommentingCampaign,
    CommentingCampaignStatus,
    CommentStatus,
    ObservedPost,
    ObservedPostStatus,
)
from sonya_web.deps import get_session

router = APIRouter(prefix="/combine/commenting", tags=["combine"])


def _validate_accounts(payload_account_ids: list[int] | None, known_ids: set[int]) -> None:
    if not payload_account_ids:
        return
    unknown = set(payload_account_ids) - known_ids
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown account_ids: {sorted(unknown)}",
        )


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[CommentingCampaign]:
    return await repo.list_campaigns(session)


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
async def create_campaign(
    payload: CampaignCreateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CommentingCampaign:
    if payload.max_delay_seconds < payload.min_delay_seconds:
        raise HTTPException(
            status_code=400,
            detail="max_delay_seconds must be >= min_delay_seconds",
        )

    owner = await account_repo.ensure_default_owner(session)
    accounts = await account_repo.list_accounts(session)
    _validate_accounts(payload.account_ids, {a.id for a in accounts})

    campaign = CommentingCampaign(
        owner_id=owner.id,
        name=payload.name,
        prompt_template=payload.prompt_template,
        target_channels=list(payload.target_channels),
        account_ids=list(payload.account_ids),
        min_delay_seconds=payload.min_delay_seconds,
        max_delay_seconds=payload.max_delay_seconds,
        max_comments_per_day=payload.max_comments_per_day,
        note=payload.note,
        status=CommentingCampaignStatus.DRAFT,
    )
    session.add(campaign)
    await session.flush()
    await session.commit()
    return campaign


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    campaign_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CommentingCampaign:
    campaign = await repo.get_campaign(session, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return campaign


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: int,
    payload: CampaignUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CommentingCampaign:
    campaign = await repo.get_campaign(session, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")

    if payload.account_ids is not None:
        accounts = await account_repo.list_accounts(session)
        _validate_accounts(payload.account_ids, {a.id for a in accounts})
        campaign.account_ids = list(payload.account_ids)

    if payload.name is not None:
        campaign.name = payload.name
    if payload.prompt_template is not None:
        campaign.prompt_template = payload.prompt_template
    if payload.target_channels is not None:
        campaign.target_channels = list(payload.target_channels)
    if payload.min_delay_seconds is not None:
        campaign.min_delay_seconds = payload.min_delay_seconds
    if payload.max_delay_seconds is not None:
        campaign.max_delay_seconds = payload.max_delay_seconds
    if payload.max_comments_per_day is not None:
        campaign.max_comments_per_day = payload.max_comments_per_day
    if payload.note is not None:
        campaign.note = payload.note

    if campaign.max_delay_seconds < campaign.min_delay_seconds:
        raise HTTPException(
            status_code=400,
            detail="max_delay_seconds must be >= min_delay_seconds",
        )

    await session.commit()
    return campaign


@router.delete("/campaigns/{campaign_id}", status_code=204)
async def delete_campaign(
    campaign_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    campaign = await repo.get_campaign(session, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    await repo.delete_campaign(session, campaign)
    await session.commit()


def _lifecycle(target: CommentingCampaignStatus):
    async def _handler(
        campaign_id: int,
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> CommentingCampaign:
        campaign = await repo.get_campaign(session, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign not found")
        if campaign.status == CommentingCampaignStatus.ARCHIVED:
            raise HTTPException(status_code=409, detail="campaign is archived")
        if target == CommentingCampaignStatus.RUNNING and not campaign.account_ids:
            raise HTTPException(
                status_code=400,
                detail="cannot start a campaign without accounts attached",
            )
        repo.transition_to_status(campaign, target)
        await session.commit()
        return campaign

    return _handler


router.post(
    "/campaigns/{campaign_id}/start",
    response_model=CampaignOut,
)(_lifecycle(CommentingCampaignStatus.RUNNING))
router.post(
    "/campaigns/{campaign_id}/pause",
    response_model=CampaignOut,
)(_lifecycle(CommentingCampaignStatus.PAUSED))
router.post(
    "/campaigns/{campaign_id}/archive",
    response_model=CampaignOut,
)(_lifecycle(CommentingCampaignStatus.ARCHIVED))


# ---------- POSTS ----------


@router.get(
    "/campaigns/{campaign_id}/posts",
    response_model=list[ObservedPostOut],
)
async def list_posts(
    campaign_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ObservedPost]:
    campaign = await repo.get_campaign(session, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return await repo.list_posts(session, campaign_id)


@router.post(
    "/campaigns/{campaign_id}/posts",
    response_model=ObservedPostOut,
    status_code=201,
)
async def push_post(
    campaign_id: int,
    payload: ObservedPostIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ObservedPost:
    campaign = await repo.get_campaign(session, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    if campaign.status == CommentingCampaignStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="campaign is archived")
    if campaign.target_channels and payload.channel not in campaign.target_channels:
        raise HTTPException(
            status_code=400,
            detail=f"channel {payload.channel!r} is not in campaign target list",
        )

    existing = await repo.get_post_by_message_id(
        session, campaign_id, payload.channel, payload.tg_message_id
    )
    if existing is not None:
        return existing

    post = ObservedPost(
        campaign_id=campaign_id,
        channel=payload.channel,
        tg_message_id=payload.tg_message_id,
        text=payload.text,
        status=ObservedPostStatus.NEW,
        observed_at=datetime.now(timezone.utc),
    )
    session.add(post)
    await session.flush()
    await session.commit()
    return post


# ---------- COMMENTS ----------


@router.post(
    "/campaigns/{campaign_id}/posts/{post_id}/render-stub",
    response_model=CommentOut,
    status_code=201,
)
async def render_stub_comment(
    campaign_id: int,
    post_id: int,
    payload: RenderStubIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Comment:
    campaign = await repo.get_campaign(session, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    if campaign.account_ids and payload.account_id not in campaign.account_ids:
        raise HTTPException(
            status_code=400,
            detail="account_id is not in campaign pool",
        )

    post = await repo.get_post_for_campaign(session, campaign_id, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="post not found in this campaign")

    account = await account_repo.get_account(session, payload.account_id)
    if account is None:
        raise HTTPException(status_code=400, detail="account does not exist")

    renderer = StubCommentRenderer(max_length=payload.max_length or 280)
    rendered = await renderer.render(campaign=campaign, post=post)

    comment = Comment(
        post_id=post.id,
        account_id=account.id,
        text=rendered.text,
        status=CommentStatus.GENERATED,
    )
    session.add(comment)
    if post.status == ObservedPostStatus.NEW:
        post.status = ObservedPostStatus.QUEUED
    await session.flush()
    await session.commit()
    return comment


@router.get(
    "/campaigns/{campaign_id}/posts/{post_id}/comments",
    response_model=list[CommentOut],
)
async def list_comments(
    campaign_id: int,
    post_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Comment]:
    post = await repo.get_post_for_campaign(session, campaign_id, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="post not found in this campaign")
    return await repo.list_comments(session, post.id)


@router.post(
    "/campaigns/{campaign_id}/posts/{post_id}/comments/{comment_id}/record",
    response_model=CommentOut,
)
async def record_comment_outcome(
    campaign_id: int,
    post_id: int,
    comment_id: int,
    payload: CommentRecordIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Comment:
    post = await repo.get_post_for_campaign(session, campaign_id, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="post not found in this campaign")

    comment = next((c for c in post.comments if c.id == comment_id), None)
    if comment is None:
        raise HTTPException(status_code=404, detail="comment not found")
    if comment.status in {
        CommentStatus.POSTED,
        CommentStatus.FAILED,
        CommentStatus.SKIPPED,
    }:
        raise HTTPException(status_code=409, detail=f"comment already {comment.status.value}")

    now = datetime.now(timezone.utc)
    if payload.text is not None:
        comment.text = payload.text
    if payload.success:
        comment.status = CommentStatus.POSTED
        comment.posted_at = now
        comment.tg_comment_id = payload.tg_comment_id
        comment.error = None
        post.status = ObservedPostStatus.COMMENTED
    else:
        comment.status = CommentStatus.FAILED
        comment.error = payload.error
        comment.posted_at = now

    await session.commit()
    return comment


__all__ = ["router"]

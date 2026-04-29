"""Commenting :class:`WorkerPlugin` — posts pre-generated comments via Telethon.

The REST router (``/render-stub`` or a future LLM-backed renderer) creates
:class:`Comment` rows with ``status=GENERATED`` for an account in the
campaign's pool. This plugin picks one such comment per ``step()``, posts
it as a reply-comment to the source channel post, and updates the
lifecycle:

* ``GENERATED`` → ``POSTED`` (and the parent ``ObservedPost`` flips to
  ``COMMENTED``) on success.
* ``GENERATED`` stays ``GENERATED`` on FloodWait (with back-off recorded
  on the limiter so future ticks honour it).
* ``GENERATED`` → ``FAILED`` (with ``error`` set) on any other exception.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sonya.combine.commenting.telethon_poster import TelethonCommentPoster
from sonya.combine.worker.plugin import WorkerContext
from sonya.db.models_combine import (
    Account,
    Comment,
    CommentingCampaign,
    CommentingCampaignStatus,
    CommentStatus,
    ObservedPost,
    ObservedPostStatus,
    Proxy,
)

logger = logging.getLogger(__name__)


def _is_flood_wait(exc: BaseException) -> bool:
    """Duck-type check for Telethon's FloodWaitError + our internal mirror."""

    return type(exc).__name__ == "FloodWaitError" and hasattr(exc, "seconds")


async def _claim_next_comment(session: AsyncSession, *, owner_id: int) -> Comment | None:
    """Pick the oldest GENERATED comment whose campaign is RUNNING.

    Loads the related ``post`` and ``post.campaign`` eagerly so the
    caller doesn't have to issue extra queries while still inside the
    same session.
    """

    stmt = (
        select(Comment)
        .join(Comment.post)
        .join(ObservedPost.campaign)
        .where(
            Comment.status == CommentStatus.GENERATED,
            CommentingCampaign.owner_id == owner_id,
            CommentingCampaign.status == CommentingCampaignStatus.RUNNING,
        )
        .order_by(Comment.id.asc())
        .options(
            selectinload(Comment.post).selectinload(ObservedPost.campaign),
        )
        .limit(1)
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


class CommentingWorkerPlugin:
    """Concrete :class:`WorkerPlugin` for the commenting module."""

    name: str = "commenting"

    def __init__(self, poster: TelethonCommentPoster | None = None) -> None:
        self._poster = poster or TelethonCommentPoster()

    async def step(self, ctx: WorkerContext) -> bool:
        async with ctx.session_factory() as session:
            comment = await _claim_next_comment(session, owner_id=ctx.owner_id)
            if comment is None:
                return False

            post = comment.post
            account = await session.get(Account, comment.account_id)
            if account is None:
                comment.status = CommentStatus.FAILED
                comment.error = f"account {comment.account_id} not found"
                await session.commit()
                return True

            proxy: Proxy | None = None
            if account.proxy_id is not None:
                proxy = await session.get(Proxy, account.proxy_id)

            try:
                client = ctx.telethon_factory.make_client(account, proxy)
            except Exception as exc:
                comment.status = CommentStatus.FAILED
                comment.error = f"client build failed: {exc}"
                await session.commit()
                logger.exception("commenting: client build failed for comment %d", comment.id)
                return True

            text = comment.text or ""
            try:
                await client.connect()
                async with ctx.rate_limiter.acquire(account.id):
                    posted = await self._poster.post(
                        client,
                        post.channel,
                        post.tg_message_id,
                        text,
                    )
            except Exception as exc:
                if _is_flood_wait(exc):
                    seconds = int(getattr(exc, "seconds", 60))
                    ctx.rate_limiter.record_flood_wait(account.id, seconds)
                    logger.warning(
                        "commenting: FloodWait %ds on account %d — comment %d stays GENERATED",
                        seconds,
                        account.id,
                        comment.id,
                    )
                    return True
                comment.status = CommentStatus.FAILED
                comment.error = str(exc)
                await session.commit()
                logger.exception("commenting: comment %d failed", comment.id)
                return True
            finally:
                disconnect = getattr(client, "disconnect", None)
                if disconnect is not None:
                    try:
                        await disconnect()
                    except Exception:
                        # Best-effort cleanup — do NOT let a failing
                        # disconnect propagate, otherwise the success
                        # path below never commits POSTED and the next
                        # tick re-sends the comment (duplicate post).
                        logger.warning(
                            "commenting: disconnect failed for account %d (ignored)",
                            account.id,
                        )

            comment.status = CommentStatus.POSTED
            comment.posted_at = datetime.now(timezone.utc)
            comment.tg_comment_id = posted.tg_comment_id
            if post.status != ObservedPostStatus.COMMENTED:
                post.status = ObservedPostStatus.COMMENTED
            await session.commit()
            logger.info(
                "commenting: posted comment %d (post %d, account %d, tg_id=%d)",
                comment.id,
                post.id,
                account.id,
                posted.tg_comment_id,
            )
            return True


__all__ = ["CommentingWorkerPlugin"]

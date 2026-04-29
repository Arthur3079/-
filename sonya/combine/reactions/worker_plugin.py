"""Worker plugin that executes planned reactions via Telethon.

The planner (backend side) has already created :class:`ReactionTarget`
rows with status ``PLANNED`` and child :class:`Reaction` rows with
status ``PENDING``. This plugin picks them up, posts the reaction
through a real (or fake) Telethon client, and transitions statuses
accordingly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from sonya.combine.reactions.telethon_poster import TelethonReactionPoster
from sonya.combine.worker.plugin import WorkerContext
from sonya.db.models_combine import (
    Account,
    Reaction,
    ReactionStatus,
    ReactionTarget,
    ReactionTargetStatus,
)

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset(
    {ReactionStatus.POSTED, ReactionStatus.FAILED, ReactionStatus.SKIPPED}
)


class ReactionsWorkerPlugin:
    """Fulfils ``WorkerPlugin`` — posts pending reactions one target at a time."""

    name: str = "reactions"

    def __init__(self, poster: TelethonReactionPoster | None = None) -> None:
        self._poster = poster or TelethonReactionPoster()

    async def step(self, ctx: WorkerContext) -> bool:
        """Claim one PLANNED target, execute its pending reactions, return True if work done."""

        async with ctx.session_factory() as session:
            # Find the first target with status PLANNED.
            result = await session.execute(
                select(ReactionTarget)
                .where(ReactionTarget.status == ReactionTargetStatus.PLANNED)
                .options(selectinload(ReactionTarget.reactions))
                .limit(1)
            )
            target = result.scalar_one_or_none()
            if target is None:
                return False

            pending = [r for r in target.reactions if r.status == ReactionStatus.PENDING]
            if not pending:
                # Edge case: all reactions already terminal — just mark done.
                target.status = ReactionTargetStatus.DONE
                await session.commit()
                return True

            did_work = False
            for reaction in pending:
                did_work = True
                await self._execute_reaction(ctx, session, target, reaction)

            # Check if all reactions are now terminal.
            await session.refresh(target, attribute_names=["reactions"])
            all_terminal = all(r.status in _TERMINAL_STATUSES for r in target.reactions)
            if all_terminal:
                target.status = ReactionTargetStatus.DONE

            await session.commit()

        return did_work

    async def _execute_reaction(
        self,
        ctx: WorkerContext,
        session: object,
        target: ReactionTarget,
        reaction: Reaction,
    ) -> None:
        """Post one reaction, updating its status in-place."""

        # Load the account (+ its proxy) for this reaction.
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import selectinload as _sel

        assert isinstance(session, AsyncSession)
        acc_result = await session.execute(
            select(Account).where(Account.id == reaction.account_id).options(_sel(Account.proxy))
        )
        account = acc_result.scalar_one_or_none()
        if account is None:
            reaction.status = ReactionStatus.FAILED
            reaction.error = f"account {reaction.account_id} not found"
            return

        try:
            client = ctx.telethon_factory.make_client(account, account.proxy)
        except Exception as exc:
            reaction.status = ReactionStatus.FAILED
            reaction.error = str(exc)
            return

        try:
            await client.connect()
            async with ctx.rate_limiter.acquire(account.id):
                await self._poster.post(
                    client,
                    target.channel,
                    target.tg_message_id,
                    reaction.emoji,
                )
            reaction.status = ReactionStatus.POSTED
            reaction.posted_at = datetime.now(timezone.utc)
        except Exception as exc:
            if _is_flood_wait(exc):
                seconds = int(getattr(exc, "seconds", 60))
                ctx.rate_limiter.record_flood_wait(account.id, seconds)
                logger.warning(
                    "FloodWait %ds for account %d — reaction %d stays pending",
                    seconds,
                    account.id,
                    reaction.id,
                )
                # Reaction stays PENDING for the next tick.
            else:
                reaction.status = ReactionStatus.FAILED
                reaction.error = str(exc)
                logger.error(
                    "Reaction %d failed: %s",
                    reaction.id,
                    exc,
                )
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass


def _is_flood_wait(exc: BaseException) -> bool:
    """Duck-type check for Telethon's FloodWaitError or our internal mirror."""
    return hasattr(exc, "seconds") and type(exc).__name__ in (
        "FloodWaitError",
        "FloodWaitError",
    )


__all__ = ["ReactionsWorkerPlugin"]

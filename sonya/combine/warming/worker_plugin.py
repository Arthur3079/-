"""Warming :class:`WorkerPlugin` — executes due warming actions.

One ``step()`` claims the oldest due :class:`WarmingAction` (status
``PENDING``, ``scheduled_at <= now``) whose parent :class:`WarmingJob`
is still ``RUNNING`` or ``PENDING`` and belongs to ``ctx.owner_id``.
The action is run via :class:`TelethonWarmingExecutor`, then the
parent job + account are reconciled via :class:`TrustScoreUpdater`:

* success → action ``DONE``, account trust_score += action.trust_delta,
  job ``RUNNING`` (and ``COMPLETED`` once every action is terminal).
* FloodWaitError → action stays ``PENDING``, rate-limiter records the
  back-off so future ticks honour it.
* other exception → action ``FAILED`` with ``error=str(exc)``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sonya.combine.warming.telethon_executor import TelethonWarmingExecutor
from sonya.combine.warming.trust import TrustScoreUpdater
from sonya.combine.worker.plugin import WorkerContext
from sonya.db.models_combine import (
    Account,
    Proxy,
    WarmingAction,
    WarmingActionStatus,
    WarmingJob,
    WarmingJobStatus,
)

logger = logging.getLogger(__name__)


def _is_flood_wait(exc: BaseException) -> bool:
    return type(exc).__name__ == "FloodWaitError" and hasattr(exc, "seconds")


_ACTIVE_JOB_STATUSES = (WarmingJobStatus.PENDING, WarmingJobStatus.RUNNING)


async def _claim_next_action(
    session: AsyncSession, *, owner_id: int, now: datetime
) -> WarmingAction | None:
    """Pick the oldest due PENDING action whose job is active.

    Eager-loads the parent job + its actions + its account so the
    plugin can pass them straight to :class:`TrustScoreUpdater` without
    extra queries.
    """

    stmt = (
        select(WarmingAction)
        .join(WarmingAction.job)
        .where(
            WarmingAction.status == WarmingActionStatus.PENDING,
            WarmingAction.scheduled_at <= now,
            WarmingJob.owner_id == owner_id,
            WarmingJob.status.in_(_ACTIVE_JOB_STATUSES),
        )
        .order_by(WarmingAction.scheduled_at.asc(), WarmingAction.id.asc())
        .options(
            selectinload(WarmingAction.job).selectinload(WarmingJob.actions),
            selectinload(WarmingAction.job).selectinload(WarmingJob.account),
        )
        .limit(1)
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


class WarmingWorkerPlugin:
    """Concrete :class:`WorkerPlugin` for the warming module."""

    name: str = "warming"

    def __init__(
        self,
        executor: TelethonWarmingExecutor | None = None,
        trust_updater: TrustScoreUpdater | None = None,
    ) -> None:
        self._executor = executor or TelethonWarmingExecutor()
        self._trust = trust_updater or TrustScoreUpdater()

    async def step(self, ctx: WorkerContext) -> bool:
        now = datetime.now(timezone.utc)
        async with ctx.session_factory() as session:
            action = await _claim_next_action(session, owner_id=ctx.owner_id, now=now)
            if action is None:
                return False

            job = action.job
            account: Account = job.account
            proxy: Proxy | None = None
            if account.proxy_id is not None:
                proxy = await session.get(Proxy, account.proxy_id)

            try:
                client = ctx.telethon_factory.make_client(account, proxy)
            except Exception as exc:
                await self._trust.complete_action(
                    session,
                    job=job,
                    action=action,
                    success=False,
                    error=f"client build failed: {exc}",
                )
                await session.commit()
                logger.exception("warming: client build failed for action %d", action.id)
                return True

            try:
                await client.connect()
                async with ctx.rate_limiter.acquire(account.id):
                    await self._executor.execute(client, action)
            except Exception as exc:
                if _is_flood_wait(exc):
                    seconds = int(getattr(exc, "seconds", 60))
                    ctx.rate_limiter.record_flood_wait(account.id, seconds)
                    logger.warning(
                        "warming: FloodWait %ds on account %d — action %d stays PENDING",
                        seconds,
                        account.id,
                        action.id,
                    )
                    return True
                await self._trust.complete_action(
                    session,
                    job=job,
                    action=action,
                    success=False,
                    error=str(exc),
                )
                await session.commit()
                logger.exception("warming: action %d failed", action.id)
                return True
            finally:
                disconnect = getattr(client, "disconnect", None)
                if disconnect is not None:
                    try:
                        await disconnect()
                    except Exception:
                        # Best-effort cleanup — a failing disconnect must
                        # not propagate, otherwise the success-path
                        # commit below is skipped and the next tick
                        # re-runs the action (e.g. duplicate join /
                        # double reaction).
                        logger.warning(
                            "warming: disconnect failed for account %d (ignored)",
                            account.id,
                        )

            await self._trust.complete_action(
                session,
                job=job,
                action=action,
                success=True,
            )
            await session.commit()
            logger.info(
                "warming: action %d (%s) done on account %d",
                action.id,
                action.kind.value,
                account.id,
            )
            return True


__all__ = ["WarmingWorkerPlugin"]

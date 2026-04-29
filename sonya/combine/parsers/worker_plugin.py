"""Parser :class:`WorkerPlugin` — claims a pending parser job and executes it.

One ``step`` = one job. The plugin:

1. Claims the oldest pending :class:`ParserJob` (atomically flipping it to
   ``RUNNING``).
2. Loads the associated :class:`Account` + :class:`Proxy`, builds a
   ``TelegramClient`` via the factory, and runs the
   :class:`TelethonExecutor`.
3. On success: inserts :class:`ParserResult` rows and marks the job
   ``COMPLETED``.
4. On ``FloodWaitError``: records the back-off and returns ``True`` (the
   runner moves on to the next tick).
5. On any other error: marks the job ``FAILED`` with the traceback.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from sonya.combine.parsers import repository as repo
from sonya.combine.parsers.telethon_executor import TelethonExecutor
from sonya.combine.worker.plugin import WorkerContext
from sonya.combine.worker.rate_limit import FloodWaitError
from sonya.db.models_combine import (
    Account,
    ParserJob,
    ParserJobStatus,
)

logger = logging.getLogger(__name__)

_executor = TelethonExecutor()


async def _claim_next_job(ctx: WorkerContext) -> ParserJob | None:
    """Atomically claim the oldest pending job for *owner_id*.

    Returns the job with ``status=RUNNING`` (already flushed) inside the
    caller's session, or ``None`` if nothing is pending.
    """
    async with ctx.session_factory() as session:
        row = (
            await session.execute(
                select(ParserJob)
                .where(
                    ParserJob.owner_id == ctx.owner_id,
                    ParserJob.status == ParserJobStatus.PENDING,
                )
                .order_by(ParserJob.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        repo.mark_running(row)
        await session.commit()
        return row


class ParserWorkerPlugin:
    """Concrete :class:`WorkerPlugin` for the parser module."""

    name: str = "parser"

    async def step(self, ctx: WorkerContext) -> bool:
        job = await _claim_next_job(ctx)
        if job is None:
            return False

        job_id = job.id

        async with ctx.session_factory() as session:
            # Re-load the job together with its account + proxy.
            loaded = (
                await session.execute(
                    select(ParserJob)
                    .where(ParserJob.id == job_id)
                    .options(selectinload(ParserJob.results))
                )
            ).scalar_one()

            account = await session.get(Account, loaded.account_id)
            if account is None:
                repo.mark_completed(loaded, success=False, error="account not found")
                await session.commit()
                return True

            proxy = None
            if account.proxy_id is not None:
                from sonya.db.models_combine import Proxy

                proxy = await session.get(Proxy, account.proxy_id)

            client = ctx.telethon_factory.make_client(account, proxy)

            try:
                await client.connect()
                async with ctx.rate_limiter.acquire(account.id):
                    results = await _executor.run(loaded, account, client=client)
            except FloodWaitError as exc:
                ctx.rate_limiter.record_flood_wait(account.id, exc.seconds)
                logger.warning(
                    "parser job %d: FloodWait %ds on account %d",
                    job_id,
                    exc.seconds,
                    account.id,
                )
                # Revert to PENDING so it can be retried later.
                loaded.status = ParserJobStatus.PENDING
                await session.commit()
                return True
            except Exception as exc:
                repo.mark_completed(loaded, success=False, error=str(exc))
                await session.commit()
                logger.exception("parser job %d failed", job_id)
                return True
            finally:
                await client.disconnect()

            await repo.append_results(session, loaded, results)
            repo.mark_completed(loaded, success=True)
            await session.commit()
            logger.info(
                "parser job %d completed: %d results",
                job_id,
                loaded.result_count,
            )
            return True


__all__ = ["ParserWorkerPlugin"]

"""Apply trust-score deltas to accounts as warming actions complete.

Pulled out into its own service because it'll later be called from:

* the REST endpoint that marks an action ``done`` (Sprint 2 — this module);
* the background executor (Sprint 2.5 / Sprint 7);
* the safety/anti-flood layer that may want to *decrement* trust on a
  ``flood_wait`` event (future).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models_combine import (
    Account,
    AccountStatus,
    WarmingAction,
    WarmingActionStatus,
    WarmingJob,
    WarmingJobStatus,
)

# Hard cap; matches the design doc — anything above is "warmed".
TRUST_SCORE_MAX = 100


class TrustScoreUpdater:
    """Apply +/- trust deltas in a single place.

    The caller is responsible for committing the surrounding transaction.
    """

    async def apply(
        self,
        session: AsyncSession,
        account: Account,
        delta: int,
        *,
        reason: str | None = None,
    ) -> int:
        """Bump :attr:`Account.trust_score` by ``delta`` (clamped to 0..100).

        Returns the new score. ``reason`` is currently only used in logs /
        future audit log; it is intentionally optional so callers don't
        have to invent one for routine bumps.
        """
        del reason
        new_score = max(0, min(TRUST_SCORE_MAX, account.trust_score + delta))
        if new_score != account.trust_score:
            account.trust_score = new_score
            await session.flush()
        return new_score

    async def complete_action(
        self,
        session: AsyncSession,
        *,
        job: WarmingJob,
        action: WarmingAction,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Mark ``action`` as done/failed and update the parent job + account.

        Side-effects on the parent ``WarmingJob``:

        * ``status`` flips to :attr:`WarmingJobStatus.RUNNING` on the first
          terminal action;
        * ``last_action_at`` is set to ``now``;
        * once every action is in a terminal state the job is marked
          :attr:`WarmingJobStatus.COMPLETED` and ``completed_at`` is set.

        And on the parent ``Account``: trust_score is bumped by
        ``action.trust_delta`` on success only.
        """

        now = datetime.now(timezone.utc)
        action.executed_at = now
        action.status = WarmingActionStatus.DONE if success else WarmingActionStatus.FAILED
        action.error = error if not success else None

        job.last_action_at = now
        if job.status == WarmingJobStatus.PENDING:
            job.status = WarmingJobStatus.RUNNING
            if job.started_at is None:
                job.started_at = now

        if success and action.trust_delta:
            await self.apply(session, job.account, action.trust_delta, reason="warming")
            if job.account.status == AccountStatus.NEW:
                job.account.status = AccountStatus.WARMING

        # Recompute completion: every action must be in a terminal state.
        terminal = {
            WarmingActionStatus.DONE,
            WarmingActionStatus.FAILED,
            WarmingActionStatus.SKIPPED,
        }
        all_terminal = all(a.status in terminal for a in job.actions)
        if all_terminal and job.status not in {
            WarmingJobStatus.COMPLETED,
            WarmingJobStatus.CANCELLED,
        }:
            job.status = WarmingJobStatus.COMPLETED
            if job.completed_at is None:
                job.completed_at = now
            if (
                job.account.status == AccountStatus.WARMING
                and job.account.trust_score >= job.target_trust_score
            ):
                job.account.status = AccountStatus.ACTIVE

        await session.flush()


__all__ = ["TRUST_SCORE_MAX", "TrustScoreUpdater"]

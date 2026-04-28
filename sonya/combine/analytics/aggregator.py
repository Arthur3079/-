"""SQL-driven aggregator for combine analytics.

One async class with a method per module (accounts/warming/parsers/
commenting/reactions) and a final :meth:`overall_summary` that composes
them. Every method does at most a handful of ``COUNT/AVG/MIN/MAX ...
GROUP BY`` round-trips — no row-level scans, no N+1.

Only the *default owner* (single-user deployment, see
``sonya.combine.accounts.repository.DEFAULT_OWNER_ID``) is reported. When
multi-tenancy lands, every method gains an ``owner_id`` argument that
defaults to the same constant — call sites stay backwards-compatible.
"""

from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.combine.accounts.repository import DEFAULT_OWNER_ID
from sonya.combine.analytics.schemas import (
    AccountsSummary,
    AccountTopRow,
    CommentingCampaignTopRow,
    CommentingSummary,
    EmojiStatusCount,
    KindCount,
    KindStatusCount,
    OverallSummary,
    ParsersSummary,
    ReactionCampaignTopRow,
    ReactionsSummary,
    StatusCount,
    TrustBucket,
    WarmingSummary,
)
from sonya.db.models_combine import (
    Account,
    AccountStatus,
    Comment,
    CommentingCampaign,
    CommentingCampaignStatus,
    CommentStatus,
    ObservedPost,
    ObservedPostStatus,
    ParserJob,
    ParserJobStatus,
    ParserKind,
    ParserResult,
    ParserResultKind,
    Proxy,
    ProxyHealth,
    Reaction,
    ReactionCampaign,
    ReactionCampaignStatus,
    ReactionStatus,
    ReactionTarget,
    ReactionTargetStatus,
    WarmingAction,
    WarmingActionKind,
    WarmingActionStatus,
    WarmingJob,
    WarmingJobStatus,
)

# Histogram boundaries for ``trust_score``. Half-open ``[lower, upper)``
# except the last bucket which includes 100 so a perfect score lands.
_TRUST_BUCKETS: tuple[tuple[int, int], ...] = (
    (0, 20),
    (20, 40),
    (40, 60),
    (60, 80),
    (80, 100),
)
# How many rows the ``top`` lists return.
_TOP_LIMIT = 10


def _zero_filled(values: list[StatusCount], order: list[str]) -> list[StatusCount]:
    """Pad ``values`` with zeros for any key in ``order`` that is missing,
    and return the result in the canonical ``order`` followed by any extras
    sorted alphabetically. Keeps the response stable when an enum gains a
    new variant in the future.
    """

    by_key = {r.status: r.count for r in values}
    out: list[StatusCount] = [StatusCount(status=key, count=by_key.pop(key, 0)) for key in order]
    out.extend(StatusCount(status=k, count=by_key[k]) for k in sorted(by_key))
    return out


class AnalyticsAggregator:
    """Compute aggregated snapshots over the combine schema."""

    def __init__(self, session: AsyncSession, *, owner_id: int = DEFAULT_OWNER_ID) -> None:
        self._session = session
        self._owner_id = owner_id

    # ------- accounts + proxies -------

    async def accounts_summary(self) -> AccountsSummary:
        session = self._session

        status_rows = await session.execute(
            select(Account.status, func.count(Account.id))
            .where(Account.owner_id == self._owner_id)
            .group_by(Account.status)
        )
        by_status_raw = [
            StatusCount(status=str(s.value if hasattr(s, "value") else s), count=int(c))
            for s, c in status_rows.all()
        ]
        by_status = _zero_filled(by_status_raw, [s.value for s in AccountStatus])
        total = sum(item.count for item in by_status)

        if total == 0:
            avg_trust = 0.0
            min_trust = 0
            max_trust = 0
        else:
            agg = (
                await session.execute(
                    select(
                        func.avg(Account.trust_score),
                        func.min(Account.trust_score),
                        func.max(Account.trust_score),
                    ).where(Account.owner_id == self._owner_id)
                )
            ).one()
            avg_trust = float(agg[0] or 0.0)
            min_trust = int(agg[1] or 0)
            max_trust = int(agg[2] or 0)

        # One round-trip for the whole histogram. Each bucket is a SUM(CASE..).
        bucket_columns = []
        for lower, upper in _TRUST_BUCKETS:
            # Last bucket is closed on both ends so trust_score==100 lands.
            cond = (
                (Account.trust_score >= lower) & (Account.trust_score <= upper)
                if upper == 100
                else (Account.trust_score >= lower) & (Account.trust_score < upper)
            )
            bucket_columns.append(func.coalesce(func.sum(case((cond, 1), else_=0)), 0))
        bucket_values = (
            await session.execute(select(*bucket_columns).where(Account.owner_id == self._owner_id))
        ).one()
        bucket_rows = [
            TrustBucket(lower=lower, upper=upper, count=int(value or 0))
            for (lower, upper), value in zip(_TRUST_BUCKETS, bucket_values, strict=True)
        ]

        top_rows = (
            await session.execute(
                select(Account.id, Account.phone, Account.status, Account.trust_score)
                .where(Account.owner_id == self._owner_id)
                .order_by(Account.trust_score.desc(), Account.id.asc())
                .limit(_TOP_LIMIT)
            )
        ).all()
        top = [
            AccountTopRow(
                id=int(row[0]),
                phone=str(row[1]),
                status=str(row[2].value if hasattr(row[2], "value") else row[2]),
                trust_score=int(row[3]),
            )
            for row in top_rows
        ]

        proxy_status_rows = await session.execute(
            select(Proxy.health, func.count(Proxy.id))
            .where(Proxy.owner_id == self._owner_id)
            .group_by(Proxy.health)
        )
        proxies_by_health_raw = [
            StatusCount(status=str(h.value if hasattr(h, "value") else h), count=int(c))
            for h, c in proxy_status_rows.all()
        ]
        proxies_by_health = _zero_filled(proxies_by_health_raw, [h.value for h in ProxyHealth])
        proxies_total = sum(item.count for item in proxies_by_health)

        return AccountsSummary(
            total=total,
            by_status=by_status,
            avg_trust=round(avg_trust, 2),
            min_trust=min_trust,
            max_trust=max_trust,
            trust_buckets=bucket_rows,
            top=top,
            proxies_total=proxies_total,
            proxies_by_health=proxies_by_health,
        )

    # ------- warming -------

    async def warming_summary(self) -> WarmingSummary:
        session = self._session

        job_rows = await session.execute(
            select(WarmingJob.status, func.count(WarmingJob.id))
            .where(WarmingJob.owner_id == self._owner_id)
            .group_by(WarmingJob.status)
        )
        jobs_by_status = _zero_filled(
            [
                StatusCount(status=str(s.value if hasattr(s, "value") else s), count=int(c))
                for s, c in job_rows.all()
            ],
            [s.value for s in WarmingJobStatus],
        )
        jobs_total = sum(item.count for item in jobs_by_status)

        action_rows = await session.execute(
            select(WarmingAction.kind, WarmingAction.status, func.count(WarmingAction.id))
            .join(WarmingJob, WarmingJob.id == WarmingAction.job_id)
            .where(WarmingJob.owner_id == self._owner_id)
            .group_by(WarmingAction.kind, WarmingAction.status)
        )
        kind_status_raw = [
            KindStatusCount(
                kind=str(k.value if hasattr(k, "value") else k),
                status=str(s.value if hasattr(s, "value") else s),
                count=int(c),
            )
            for k, s, c in action_rows.all()
        ]
        ordered_kinds = [k.value for k in WarmingActionKind]
        ordered_statuses = [s.value for s in WarmingActionStatus]
        actions_by_kind_status: list[KindStatusCount] = []
        seen = {(r.kind, r.status): r.count for r in kind_status_raw}
        for k in ordered_kinds:
            for s in ordered_statuses:
                actions_by_kind_status.append(
                    KindStatusCount(kind=k, status=s, count=int(seen.pop((k, s), 0)))
                )
        # Append any unexpected enum combos so we don't silently drop them.
        for (k, s), c in sorted(seen.items()):
            actions_by_kind_status.append(KindStatusCount(kind=k, status=s, count=int(c)))
        actions_total = sum(item.count for item in actions_by_kind_status)

        return WarmingSummary(
            jobs_total=jobs_total,
            jobs_by_status=jobs_by_status,
            actions_total=actions_total,
            actions_by_kind_status=actions_by_kind_status,
        )

    # ------- parsers -------

    async def parsers_summary(self) -> ParsersSummary:
        session = self._session

        status_rows = await session.execute(
            select(ParserJob.status, func.count(ParserJob.id))
            .where(ParserJob.owner_id == self._owner_id)
            .group_by(ParserJob.status)
        )
        jobs_by_status = _zero_filled(
            [
                StatusCount(status=str(s.value if hasattr(s, "value") else s), count=int(c))
                for s, c in status_rows.all()
            ],
            [s.value for s in ParserJobStatus],
        )
        jobs_total = sum(item.count for item in jobs_by_status)

        kind_rows = await session.execute(
            select(ParserJob.kind, func.count(ParserJob.id))
            .where(ParserJob.owner_id == self._owner_id)
            .group_by(ParserJob.kind)
        )
        jobs_by_kind_raw = {
            str(k.value if hasattr(k, "value") else k): int(c) for k, c in kind_rows.all()
        }
        jobs_by_kind = [
            KindCount(kind=k.value, count=jobs_by_kind_raw.get(k.value, 0)) for k in ParserKind
        ]

        result_kind_rows = await session.execute(
            select(ParserResult.kind, func.count(ParserResult.id))
            .join(ParserJob, ParserJob.id == ParserResult.job_id)
            .where(ParserJob.owner_id == self._owner_id)
            .group_by(ParserResult.kind)
        )
        results_by_kind_raw = {
            str(k.value if hasattr(k, "value") else k): int(c) for k, c in result_kind_rows.all()
        }
        results_by_kind = [
            KindCount(kind=k.value, count=results_by_kind_raw.get(k.value, 0))
            for k in ParserResultKind
        ]

        # Sum of result_count per parser kind (cheap — the column is denormalised).
        sum_rows = await session.execute(
            select(ParserJob.kind, func.coalesce(func.sum(ParserJob.result_count), 0))
            .where(ParserJob.owner_id == self._owner_id)
            .group_by(ParserJob.kind)
        )
        results_by_job_kind_raw = {
            str(k.value if hasattr(k, "value") else k): int(c) for k, c in sum_rows.all()
        }
        results_by_job_kind = [
            KindCount(kind=k.value, count=results_by_job_kind_raw.get(k.value, 0))
            for k in ParserKind
        ]

        results_total = sum(item.count for item in results_by_kind)

        return ParsersSummary(
            jobs_total=jobs_total,
            jobs_by_status=jobs_by_status,
            jobs_by_kind=jobs_by_kind,
            results_total=results_total,
            results_by_kind=results_by_kind,
            results_by_job_kind=results_by_job_kind,
        )

    # ------- commenting -------

    async def commenting_summary(self) -> CommentingSummary:
        session = self._session

        camp_rows = await session.execute(
            select(CommentingCampaign.status, func.count(CommentingCampaign.id))
            .where(CommentingCampaign.owner_id == self._owner_id)
            .group_by(CommentingCampaign.status)
        )
        campaigns_by_status = _zero_filled(
            [
                StatusCount(status=str(s.value if hasattr(s, "value") else s), count=int(c))
                for s, c in camp_rows.all()
            ],
            [s.value for s in CommentingCampaignStatus],
        )
        campaigns_total = sum(item.count for item in campaigns_by_status)

        post_rows = await session.execute(
            select(ObservedPost.status, func.count(ObservedPost.id))
            .join(
                CommentingCampaign,
                CommentingCampaign.id == ObservedPost.campaign_id,
            )
            .where(CommentingCampaign.owner_id == self._owner_id)
            .group_by(ObservedPost.status)
        )
        posts_by_status = _zero_filled(
            [
                StatusCount(status=str(s.value if hasattr(s, "value") else s), count=int(c))
                for s, c in post_rows.all()
            ],
            [s.value for s in ObservedPostStatus],
        )
        posts_total = sum(item.count for item in posts_by_status)

        comment_rows = await session.execute(
            select(Comment.status, func.count(Comment.id))
            .join(ObservedPost, ObservedPost.id == Comment.post_id)
            .join(
                CommentingCampaign,
                CommentingCampaign.id == ObservedPost.campaign_id,
            )
            .where(CommentingCampaign.owner_id == self._owner_id)
            .group_by(Comment.status)
        )
        comments_by_status = _zero_filled(
            [
                StatusCount(status=str(s.value if hasattr(s, "value") else s), count=int(c))
                for s, c in comment_rows.all()
            ],
            [s.value for s in CommentStatus],
        )
        comments_total = sum(item.count for item in comments_by_status)

        top_rows = (
            await session.execute(
                select(
                    CommentingCampaign.id,
                    CommentingCampaign.name,
                    CommentingCampaign.status,
                    func.coalesce(
                        func.sum(case((Comment.status == CommentStatus.POSTED, 1), else_=0)),
                        0,
                    ).label("posted"),
                )
                .outerjoin(ObservedPost, ObservedPost.campaign_id == CommentingCampaign.id)
                .outerjoin(Comment, Comment.post_id == ObservedPost.id)
                .where(CommentingCampaign.owner_id == self._owner_id)
                .group_by(
                    CommentingCampaign.id,
                    CommentingCampaign.name,
                    CommentingCampaign.status,
                )
                .order_by(func.coalesce(func.count(Comment.id), 0).desc())
                .limit(_TOP_LIMIT)
            )
        ).all()
        top = [
            CommentingCampaignTopRow(
                id=int(row[0]),
                name=str(row[1]),
                status=str(row[2].value if hasattr(row[2], "value") else row[2]),
                posted_count=int(row[3] or 0),
            )
            for row in top_rows
        ]

        return CommentingSummary(
            campaigns_total=campaigns_total,
            campaigns_by_status=campaigns_by_status,
            posts_total=posts_total,
            posts_by_status=posts_by_status,
            comments_total=comments_total,
            comments_by_status=comments_by_status,
            top=top,
        )

    # ------- reactions -------

    async def reactions_summary(self) -> ReactionsSummary:
        session = self._session

        camp_rows = await session.execute(
            select(ReactionCampaign.status, func.count(ReactionCampaign.id))
            .where(ReactionCampaign.owner_id == self._owner_id)
            .group_by(ReactionCampaign.status)
        )
        campaigns_by_status = _zero_filled(
            [
                StatusCount(status=str(s.value if hasattr(s, "value") else s), count=int(c))
                for s, c in camp_rows.all()
            ],
            [s.value for s in ReactionCampaignStatus],
        )
        campaigns_total = sum(item.count for item in campaigns_by_status)

        target_rows = await session.execute(
            select(ReactionTarget.status, func.count(ReactionTarget.id))
            .join(
                ReactionCampaign,
                ReactionCampaign.id == ReactionTarget.campaign_id,
            )
            .where(ReactionCampaign.owner_id == self._owner_id)
            .group_by(ReactionTarget.status)
        )
        targets_by_status = _zero_filled(
            [
                StatusCount(status=str(s.value if hasattr(s, "value") else s), count=int(c))
                for s, c in target_rows.all()
            ],
            [s.value for s in ReactionTargetStatus],
        )
        targets_total = sum(item.count for item in targets_by_status)

        reaction_status_rows = await session.execute(
            select(Reaction.status, func.count(Reaction.id))
            .join(ReactionTarget, ReactionTarget.id == Reaction.target_id)
            .join(
                ReactionCampaign,
                ReactionCampaign.id == ReactionTarget.campaign_id,
            )
            .where(ReactionCampaign.owner_id == self._owner_id)
            .group_by(Reaction.status)
        )
        reactions_by_status = _zero_filled(
            [
                StatusCount(status=str(s.value if hasattr(s, "value") else s), count=int(c))
                for s, c in reaction_status_rows.all()
            ],
            [s.value for s in ReactionStatus],
        )
        reactions_total = sum(item.count for item in reactions_by_status)

        emoji_rows = await session.execute(
            select(Reaction.emoji, Reaction.status, func.count(Reaction.id))
            .join(ReactionTarget, ReactionTarget.id == Reaction.target_id)
            .join(
                ReactionCampaign,
                ReactionCampaign.id == ReactionTarget.campaign_id,
            )
            .where(ReactionCampaign.owner_id == self._owner_id)
            .group_by(Reaction.emoji, Reaction.status)
            .order_by(Reaction.emoji.asc())
        )
        reactions_by_emoji_status = [
            EmojiStatusCount(
                emoji=str(emoji),
                status=str(s.value if hasattr(s, "value") else s),
                count=int(c),
            )
            for emoji, s, c in emoji_rows.all()
        ]

        top_rows = (
            await session.execute(
                select(
                    ReactionCampaign.id,
                    ReactionCampaign.name,
                    ReactionCampaign.status,
                    func.coalesce(
                        func.sum(case((Reaction.status == ReactionStatus.POSTED, 1), else_=0)),
                        0,
                    ).label("posted"),
                )
                .outerjoin(ReactionTarget, ReactionTarget.campaign_id == ReactionCampaign.id)
                .outerjoin(Reaction, Reaction.target_id == ReactionTarget.id)
                .where(ReactionCampaign.owner_id == self._owner_id)
                .group_by(
                    ReactionCampaign.id,
                    ReactionCampaign.name,
                    ReactionCampaign.status,
                )
                .order_by(func.coalesce(func.count(Reaction.id), 0).desc())
                .limit(_TOP_LIMIT)
            )
        ).all()
        top = [
            ReactionCampaignTopRow(
                id=int(row[0]),
                name=str(row[1]),
                status=str(row[2].value if hasattr(row[2], "value") else row[2]),
                posted_count=int(row[3] or 0),
            )
            for row in top_rows
        ]

        return ReactionsSummary(
            campaigns_total=campaigns_total,
            campaigns_by_status=campaigns_by_status,
            targets_total=targets_total,
            targets_by_status=targets_by_status,
            reactions_total=reactions_total,
            reactions_by_status=reactions_by_status,
            reactions_by_emoji_status=reactions_by_emoji_status,
            top=top,
        )

    # ------- composed -------

    async def overall_summary(self) -> OverallSummary:
        return OverallSummary(
            accounts=await self.accounts_summary(),
            warming=await self.warming_summary(),
            parsers=await self.parsers_summary(),
            commenting=await self.commenting_summary(),
            reactions=await self.reactions_summary(),
        )


__all__ = ["AnalyticsAggregator"]

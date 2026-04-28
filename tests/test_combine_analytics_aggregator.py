"""Unit tests for ``sonya.combine.analytics.aggregator.AnalyticsAggregator``.

The aggregator is exercised against an in-memory SQLite that mirrors the
production schema so we can verify the actual GROUP BY/SUM(CASE) shape of
each query without spinning up a FastAPI app.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sonya.combine.accounts.repository import DEFAULT_OWNER_ID
from sonya.combine.analytics import AnalyticsAggregator
from sonya.db.base import Base
from sonya.db.models_combine import (  # noqa: F401 — register tables
    Account,
    AccountRole,
    AccountStatus,
    Comment,
    CommentingCampaign,
    CommentingCampaignStatus,
    CommentStatus,
    ObservedPost,
    ObservedPostStatus,
    Owner,
    ParserJob,
    ParserJobStatus,
    ParserKind,
    ParserResult,
    ParserResultKind,
    Proxy,
    ProxyHealth,
    ProxyType,
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


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        s.add(Owner(id=DEFAULT_OWNER_ID, name="default"))
        await s.flush()
        yield s
    await engine.dispose()


def _now() -> datetime:
    return datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


async def _add_account(
    session: AsyncSession,
    *,
    phone: str,
    status: AccountStatus = AccountStatus.NEW,
    trust: int = 0,
    role: AccountRole = AccountRole.MULTI,
) -> Account:
    acc = Account(
        owner_id=DEFAULT_OWNER_ID,
        phone=phone,
        status=status,
        trust_score=trust,
        role=role,
    )
    session.add(acc)
    await session.flush()
    return acc


# --------------------------- empty-state ---------------------------


@pytest.mark.asyncio
async def test_empty_database_yields_zeros(session: AsyncSession) -> None:
    agg = AnalyticsAggregator(session)
    overall = await agg.overall_summary()

    assert overall.accounts.total == 0
    assert all(item.count == 0 for item in overall.accounts.by_status)
    assert overall.accounts.avg_trust == 0
    assert overall.accounts.min_trust == 0
    assert overall.accounts.max_trust == 0
    assert all(b.count == 0 for b in overall.accounts.trust_buckets)
    assert overall.accounts.top == []
    assert overall.accounts.proxies_total == 0

    assert overall.warming.jobs_total == 0
    assert overall.warming.actions_total == 0

    assert overall.parsers.jobs_total == 0
    assert overall.parsers.results_total == 0

    assert overall.commenting.campaigns_total == 0
    assert overall.commenting.posts_total == 0
    assert overall.commenting.comments_total == 0
    assert overall.commenting.top == []

    assert overall.reactions.campaigns_total == 0
    assert overall.reactions.targets_total == 0
    assert overall.reactions.reactions_total == 0
    assert overall.reactions.top == []


# --------------------------- accounts ---------------------------


@pytest.mark.asyncio
async def test_accounts_summary_counts_by_status_and_buckets(session: AsyncSession) -> None:
    await _add_account(session, phone="+1", status=AccountStatus.ACTIVE, trust=10)
    await _add_account(session, phone="+2", status=AccountStatus.ACTIVE, trust=25)
    await _add_account(session, phone="+3", status=AccountStatus.WARMING, trust=55)
    await _add_account(session, phone="+4", status=AccountStatus.BANNED, trust=85)
    await _add_account(session, phone="+5", status=AccountStatus.ACTIVE, trust=100)
    session.add(
        Proxy(
            owner_id=DEFAULT_OWNER_ID,
            type=ProxyType.SOCKS5,
            host="h",
            port=1080,
            health=ProxyHealth.OK,
        )
    )
    session.add(
        Proxy(
            owner_id=DEFAULT_OWNER_ID,
            type=ProxyType.SOCKS5,
            host="h2",
            port=1081,
            health=ProxyHealth.DEAD,
        )
    )
    await session.flush()

    summary = await AnalyticsAggregator(session).accounts_summary()

    assert summary.total == 5
    by_status = {item.status: item.count for item in summary.by_status}
    assert by_status["active"] == 3
    assert by_status["warming"] == 1
    assert by_status["banned"] == 1
    assert by_status["new"] == 0  # zero-fill works

    assert summary.min_trust == 10
    assert summary.max_trust == 100
    assert summary.avg_trust == pytest.approx((10 + 25 + 55 + 85 + 100) / 5)

    bucket_counts = {(b.lower, b.upper): b.count for b in summary.trust_buckets}
    assert bucket_counts[(0, 20)] == 1  # trust=10
    assert bucket_counts[(20, 40)] == 1  # trust=25
    assert bucket_counts[(40, 60)] == 1  # trust=55
    assert bucket_counts[(60, 80)] == 0
    assert bucket_counts[(80, 100)] == 2  # trust=85, 100 (closed)

    # top is sorted by trust desc
    assert [r.trust_score for r in summary.top] == [100, 85, 55, 25, 10]
    assert summary.top[0].phone == "+5"

    proxies_by_health = {item.status: item.count for item in summary.proxies_by_health}
    assert summary.proxies_total == 2
    assert proxies_by_health["ok"] == 1
    assert proxies_by_health["dead"] == 1
    assert proxies_by_health["unknown"] == 0


# --------------------------- warming ---------------------------


@pytest.mark.asyncio
async def test_warming_summary_groups_jobs_and_actions(session: AsyncSession) -> None:
    acc = await _add_account(session, phone="+1")
    job_running = WarmingJob(
        owner_id=DEFAULT_OWNER_ID, account_id=acc.id, status=WarmingJobStatus.RUNNING
    )
    job_done = WarmingJob(
        owner_id=DEFAULT_OWNER_ID, account_id=acc.id, status=WarmingJobStatus.COMPLETED
    )
    session.add_all([job_running, job_done])
    await session.flush()

    actions = [
        WarmingAction(
            job_id=job_running.id,
            kind=WarmingActionKind.SUBSCRIBE_CHANNEL,
            scheduled_at=_now(),
            status=WarmingActionStatus.DONE,
        ),
        WarmingAction(
            job_id=job_running.id,
            kind=WarmingActionKind.SUBSCRIBE_CHANNEL,
            scheduled_at=_now(),
            status=WarmingActionStatus.FAILED,
        ),
        WarmingAction(
            job_id=job_done.id,
            kind=WarmingActionKind.READ_HISTORY,
            scheduled_at=_now(),
            status=WarmingActionStatus.DONE,
        ),
    ]
    session.add_all(actions)
    await session.flush()

    summary = await AnalyticsAggregator(session).warming_summary()

    by_status = {item.status: item.count for item in summary.jobs_by_status}
    assert summary.jobs_total == 2
    assert by_status["running"] == 1
    assert by_status["completed"] == 1
    assert by_status["pending"] == 0

    assert summary.actions_total == 3
    by_kind_status = {(r.kind, r.status): r.count for r in summary.actions_by_kind_status}
    assert by_kind_status[("subscribe_channel", "done")] == 1
    assert by_kind_status[("subscribe_channel", "failed")] == 1
    assert by_kind_status[("read_history", "done")] == 1
    assert by_kind_status[("react_post", "pending")] == 0  # zero-fill


# --------------------------- parsers ---------------------------


@pytest.mark.asyncio
async def test_parsers_summary_counts_jobs_and_results(session: AsyncSession) -> None:
    acc = await _add_account(session, phone="+1")
    job_a = ParserJob(
        owner_id=DEFAULT_OWNER_ID,
        account_id=acc.id,
        kind=ParserKind.USERS_IN_CHAT,
        target="@news",
        status=ParserJobStatus.COMPLETED,
        result_count=2,
    )
    job_b = ParserJob(
        owner_id=DEFAULT_OWNER_ID,
        account_id=acc.id,
        kind=ParserKind.CHAT_HISTORY,
        target="@news",
        status=ParserJobStatus.PENDING,
        result_count=0,
    )
    session.add_all([job_a, job_b])
    await session.flush()
    session.add_all(
        [
            ParserResult(job_id=job_a.id, kind=ParserResultKind.USER, tg_id=1),
            ParserResult(job_id=job_a.id, kind=ParserResultKind.USER, tg_id=2),
        ]
    )
    await session.flush()

    summary = await AnalyticsAggregator(session).parsers_summary()

    assert summary.jobs_total == 2
    by_status = {item.status: item.count for item in summary.jobs_by_status}
    assert by_status["completed"] == 1
    assert by_status["pending"] == 1
    assert by_status["failed"] == 0

    by_kind = {item.kind: item.count for item in summary.jobs_by_kind}
    assert by_kind["users_in_chat"] == 1
    assert by_kind["chat_history"] == 1
    assert by_kind["users_by_message"] == 0

    assert summary.results_total == 2
    results_by_kind = {item.kind: item.count for item in summary.results_by_kind}
    assert results_by_kind["user"] == 2
    assert results_by_kind["channel"] == 0

    by_job_kind = {item.kind: item.count for item in summary.results_by_job_kind}
    assert by_job_kind["users_in_chat"] == 2  # sum of result_count
    assert by_job_kind["chat_history"] == 0


# --------------------------- commenting ---------------------------


@pytest.mark.asyncio
async def test_commenting_summary_groups_lifecycle(session: AsyncSession) -> None:
    acc = await _add_account(session, phone="+1")
    camp_a = CommentingCampaign(
        owner_id=DEFAULT_OWNER_ID,
        name="A",
        status=CommentingCampaignStatus.RUNNING,
        target_channels=["@a"],
        account_ids=[acc.id],
        prompt_template="t",
    )
    camp_b = CommentingCampaign(
        owner_id=DEFAULT_OWNER_ID,
        name="B",
        status=CommentingCampaignStatus.DRAFT,
        target_channels=["@b"],
        account_ids=[acc.id],
        prompt_template="t",
    )
    session.add_all([camp_a, camp_b])
    await session.flush()

    post_a = ObservedPost(
        campaign_id=camp_a.id,
        channel="@a",
        tg_message_id=1,
        status=ObservedPostStatus.COMMENTED,
        observed_at=_now(),
    )
    post_b = ObservedPost(
        campaign_id=camp_a.id,
        channel="@a",
        tg_message_id=2,
        status=ObservedPostStatus.NEW,
        observed_at=_now(),
    )
    session.add_all([post_a, post_b])
    await session.flush()

    session.add_all(
        [
            Comment(
                post_id=post_a.id,
                account_id=acc.id,
                status=CommentStatus.POSTED,
                text="ok",
            ),
            Comment(
                post_id=post_a.id,
                account_id=acc.id,
                status=CommentStatus.POSTED,
                text="ok2",
            ),
            Comment(
                post_id=post_b.id,
                account_id=acc.id,
                status=CommentStatus.FAILED,
                text=None,
            ),
        ]
    )
    await session.flush()

    summary = await AnalyticsAggregator(session).commenting_summary()

    assert summary.campaigns_total == 2
    by_camp = {item.status: item.count for item in summary.campaigns_by_status}
    assert by_camp["running"] == 1
    assert by_camp["draft"] == 1

    by_post = {item.status: item.count for item in summary.posts_by_status}
    assert summary.posts_total == 2
    assert by_post["commented"] == 1
    assert by_post["new"] == 1

    by_comment = {item.status: item.count for item in summary.comments_by_status}
    assert summary.comments_total == 3
    assert by_comment["posted"] == 2
    assert by_comment["failed"] == 1
    assert by_comment["pending"] == 0

    top_by_id = {row.id: row for row in summary.top}
    assert top_by_id[camp_a.id].posted_count == 2
    assert top_by_id[camp_b.id].posted_count == 0


# --------------------------- reactions ---------------------------


@pytest.mark.asyncio
async def test_reactions_summary_groups_lifecycle(session: AsyncSession) -> None:
    acc = await _add_account(session, phone="+1")
    camp = ReactionCampaign(
        owner_id=DEFAULT_OWNER_ID,
        name="R1",
        status=ReactionCampaignStatus.RUNNING,
        target_channels=["@a"],
        account_ids=[acc.id],
        emojis=["👍", "🔥"],
    )
    session.add(camp)
    await session.flush()

    target_done = ReactionTarget(
        campaign_id=camp.id,
        channel="@a",
        tg_message_id=1,
        status=ReactionTargetStatus.DONE,
        observed_at=_now(),
    )
    target_pending = ReactionTarget(
        campaign_id=camp.id,
        channel="@a",
        tg_message_id=2,
        status=ReactionTargetStatus.PENDING,
        observed_at=_now(),
    )
    session.add_all([target_done, target_pending])
    await session.flush()

    session.add_all(
        [
            Reaction(
                target_id=target_done.id,
                account_id=acc.id,
                emoji="👍",
                status=ReactionStatus.POSTED,
            ),
            Reaction(
                target_id=target_done.id,
                account_id=acc.id,
                emoji="🔥",
                status=ReactionStatus.POSTED,
            ),
            Reaction(
                target_id=target_done.id,
                account_id=acc.id,
                emoji="👍",
                status=ReactionStatus.FAILED,
            ),
        ]
    )
    await session.flush()

    summary = await AnalyticsAggregator(session).reactions_summary()

    assert summary.campaigns_total == 1
    by_camp = {item.status: item.count for item in summary.campaigns_by_status}
    assert by_camp["running"] == 1
    assert by_camp["draft"] == 0

    by_target = {item.status: item.count for item in summary.targets_by_status}
    assert summary.targets_total == 2
    assert by_target["done"] == 1
    assert by_target["pending"] == 1

    by_reaction = {item.status: item.count for item in summary.reactions_by_status}
    assert summary.reactions_total == 3
    assert by_reaction["posted"] == 2
    assert by_reaction["failed"] == 1

    by_emoji_status = {(r.emoji, r.status): r.count for r in summary.reactions_by_emoji_status}
    assert by_emoji_status[("👍", "posted")] == 1
    assert by_emoji_status[("👍", "failed")] == 1
    assert by_emoji_status[("🔥", "posted")] == 1

    assert summary.top[0].id == camp.id
    assert summary.top[0].posted_count == 2


# --------------------------- multi-tenant scoping ---------------------------


@pytest.mark.asyncio
async def test_aggregator_scopes_to_owner_id(session: AsyncSession) -> None:
    other = Owner(id=2, name="other")
    session.add(other)
    await session.flush()

    # Default owner: 1 account
    await _add_account(session, phone="+1", status=AccountStatus.ACTIVE, trust=42)
    # Other owner: 2 accounts — must NOT show up in default-owner aggregator.
    session.add(Account(owner_id=2, phone="+2", status=AccountStatus.ACTIVE, trust_score=50))
    session.add(Account(owner_id=2, phone="+3", status=AccountStatus.BANNED, trust_score=10))
    await session.flush()

    default_summary = await AnalyticsAggregator(session).accounts_summary()
    other_summary = await AnalyticsAggregator(session, owner_id=2).accounts_summary()

    assert default_summary.total == 1
    assert default_summary.top[0].phone == "+1"
    assert other_summary.total == 2
    assert {row.phone for row in other_summary.top} == {"+2", "+3"}

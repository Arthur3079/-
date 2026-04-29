"""Unit tests for :class:`CommentingWorkerPlugin` — full lifecycle on SQLite."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sonya.combine.commenting.telethon_poster import (
    PostedComment,
    TelethonCommentPoster,
)
from sonya.combine.commenting.worker_plugin import CommentingWorkerPlugin
from sonya.combine.worker.plugin import WorkerContext
from sonya.combine.worker.rate_limit import AccountRateLimiter
from sonya.db.base import Base
from sonya.db.models_combine import (
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
    Proxy,
)

# ----------------------- fakes -----------------------


class _FakeFloodWaitError(Exception):
    """Mimics telethon.errors.FloodWaitError — duck-typed via __name__."""

    def __init__(self, seconds: int) -> None:
        super().__init__(f"flood wait {seconds}s")
        self.seconds = seconds


_FakeFloodWaitError.__name__ = "FloodWaitError"


@dataclass
class _FakeClient:
    connected: bool = False
    disconnected: bool = False
    account_id: int | None = None

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True


class _FakePoster(TelethonCommentPoster):
    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any, int, str]] = []
        self._raise_for: dict[int, Exception] = {}
        self._next_id = 1000

    def raise_on_account(self, account_id: int, exc: Exception) -> None:
        self._raise_for[account_id] = exc

    async def post(
        self,
        client: Any,
        channel: Any,
        tg_message_id: int,
        text: str,
    ) -> PostedComment:
        self.calls.append((client, channel, tg_message_id, text))
        account_id = getattr(client, "account_id", None)
        if account_id is not None and account_id in self._raise_for:
            raise self._raise_for.pop(account_id)
        self._next_id += 1
        return PostedComment(tg_comment_id=self._next_id)


@dataclass
class _FakeFactory:
    clients: dict[int, _FakeClient] = field(default_factory=dict)

    def make_client(self, account: Account, proxy: Proxy | None = None) -> _FakeClient:
        client = self.clients.get(account.id, _FakeClient())
        client.account_id = account.id
        return client


# ----------------------- fixtures -----------------------


@pytest_asyncio.fixture
async def db_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        s.add(Owner(id=1, name="default"))
        await s.commit()
    yield factory
    await engine.dispose()


async def _seed_campaign_post_comment(
    sf: async_sessionmaker[AsyncSession],
    *,
    campaign_status: CommentingCampaignStatus = CommentingCampaignStatus.RUNNING,
    comment_status: CommentStatus = CommentStatus.GENERATED,
    account_id: int = 1,
    text: str = "stub comment",
) -> tuple[int, int, int]:
    """Insert one campaign + post + account + comment. Returns (campaign_id, post_id, comment_id)."""
    async with sf() as s:
        s.add(
            Account(
                id=account_id,
                owner_id=1,
                phone=f"+100000000{account_id:02d}",
                role=AccountRole.MULTI,
                status=AccountStatus.ACTIVE,
                session_blob=b"FAKE_SESSION",
            )
        )
        campaign = CommentingCampaign(
            id=1,
            owner_id=1,
            name="c1",
            status=campaign_status,
            target_channels=["@news"],
            account_ids=[account_id],
            prompt_template="say something nice about {post}",
            min_delay_seconds=60,
            max_delay_seconds=300,
            max_comments_per_day=20,
        )
        s.add(campaign)
        await s.flush()
        post = ObservedPost(
            id=1,
            campaign_id=campaign.id,
            channel="@news",
            tg_message_id=42,
            text="hello world",
            status=ObservedPostStatus.QUEUED,
            observed_at=datetime.now(timezone.utc),
        )
        s.add(post)
        await s.flush()
        comment = Comment(
            id=1,
            post_id=post.id,
            account_id=account_id,
            text=text,
            status=comment_status,
        )
        s.add(comment)
        await s.commit()
        return campaign.id, post.id, comment.id


def _ctx(
    sf: async_sessionmaker[AsyncSession],
    *,
    factory: _FakeFactory | None = None,
    rate_limiter: AccountRateLimiter | None = None,
) -> WorkerContext:
    return WorkerContext(
        session_factory=sf,
        telethon_factory=factory or _FakeFactory(),  # type: ignore[arg-type]
        rate_limiter=rate_limiter or AccountRateLimiter(),
        owner_id=1,
    )


# ----------------------- tests -----------------------


@pytest.mark.asyncio
async def test_step_no_work(db_factory: async_sessionmaker[AsyncSession]) -> None:
    plugin = CommentingWorkerPlugin(poster=_FakePoster())
    did = await plugin.step(_ctx(db_factory))
    assert did is False


@pytest.mark.asyncio
async def test_step_success_marks_posted_and_post_commented(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, post_id, comment_id = await _seed_campaign_post_comment(db_factory)
    poster = _FakePoster()
    plugin = CommentingWorkerPlugin(poster=poster)

    did = await plugin.step(_ctx(db_factory))
    assert did is True

    async with db_factory() as s:
        comment = await s.get(Comment, comment_id)
        post = await s.get(ObservedPost, post_id)
        assert comment is not None and post is not None
        assert comment.status == CommentStatus.POSTED
        assert comment.posted_at is not None
        assert comment.tg_comment_id == 1001
        assert post.status == ObservedPostStatus.COMMENTED

    assert len(poster.calls) == 1
    _, channel, tg_id, text = poster.calls[0]
    assert channel == "@news"
    assert tg_id == 42
    assert text == "stub comment"


@pytest.mark.asyncio
async def test_step_skips_pending_campaign(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Comments under a non-RUNNING campaign should be ignored."""
    await _seed_campaign_post_comment(
        db_factory,
        campaign_status=CommentingCampaignStatus.PAUSED,
    )
    plugin = CommentingWorkerPlugin(poster=_FakePoster())
    did = await plugin.step(_ctx(db_factory))
    assert did is False


@pytest.mark.asyncio
async def test_step_skips_non_generated_comment(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_campaign_post_comment(
        db_factory,
        comment_status=CommentStatus.PENDING,
    )
    plugin = CommentingWorkerPlugin(poster=_FakePoster())
    did = await plugin.step(_ctx(db_factory))
    assert did is False


@pytest.mark.asyncio
async def test_step_flood_wait_keeps_comment_generated(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, _, comment_id = await _seed_campaign_post_comment(db_factory)
    poster = _FakePoster()
    poster.raise_on_account(1, _FakeFloodWaitError(seconds=42))
    rl = AccountRateLimiter()
    plugin = CommentingWorkerPlugin(poster=poster)

    did = await plugin.step(_ctx(db_factory, rate_limiter=rl))
    assert did is True

    async with db_factory() as s:
        comment = await s.get(Comment, comment_id)
        assert comment is not None
        assert comment.status == CommentStatus.GENERATED
        assert comment.error is None
    assert rl.is_flood_blocked(1) is True


@pytest.mark.asyncio
async def test_step_failure_marks_failed(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, _, comment_id = await _seed_campaign_post_comment(db_factory)
    poster = _FakePoster()
    poster.raise_on_account(1, RuntimeError("nope"))
    plugin = CommentingWorkerPlugin(poster=poster)

    did = await plugin.step(_ctx(db_factory))
    assert did is True

    async with db_factory() as s:
        comment = await s.get(Comment, comment_id)
        assert comment is not None
        assert comment.status == CommentStatus.FAILED
        assert comment.error is not None
        assert "nope" in comment.error


@pytest.mark.asyncio
async def test_step_missing_account_marks_failed(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, _, _ = await _seed_campaign_post_comment(db_factory, account_id=1)
    # Wipe the account row but leave the comment
    async with db_factory() as s:
        acc = await s.get(Account, 1)
        assert acc is not None
        await s.delete(acc)
        await s.commit()

    plugin = CommentingWorkerPlugin(poster=_FakePoster())
    did = await plugin.step(_ctx(db_factory))
    assert did is True

    async with db_factory() as s:
        rows = (await s.execute(select(Comment))).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == CommentStatus.FAILED
        assert "account" in (rows[0].error or "").lower()


@pytest.mark.asyncio
async def test_step_disconnect_failure_does_not_block_commit(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    """If ``client.disconnect()`` raises after a successful post, the comment
    must still be marked POSTED — otherwise the next tick would re-send it
    and produce a duplicate Telegram comment.
    """
    _, post_id, comment_id = await _seed_campaign_post_comment(db_factory)

    class _BrokenDisconnectClient(_FakeClient):
        async def disconnect(self) -> None:  # type: ignore[override]
            raise RuntimeError("transport already closed")

    factory = _FakeFactory(clients={1: _BrokenDisconnectClient(account_id=1)})
    poster = _FakePoster()
    plugin = CommentingWorkerPlugin(poster=poster)

    did = await plugin.step(_ctx(db_factory, factory=factory))
    assert did is True
    assert len(poster.calls) == 1

    async with db_factory() as s:
        comment = await s.get(Comment, comment_id)
        post = await s.get(ObservedPost, post_id)
        assert comment is not None and post is not None
        assert comment.status == CommentStatus.POSTED
        assert comment.tg_comment_id is not None
        assert post.status == ObservedPostStatus.COMMENTED


@pytest.mark.asyncio
async def test_step_picks_oldest_comment_first(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    """When multiple GENERATED comments exist, take the lowest-id one."""
    await _seed_campaign_post_comment(db_factory, account_id=1, text="first")
    # Add a second comment to the same post
    async with db_factory() as s:
        s.add(
            Comment(
                id=2,
                post_id=1,
                account_id=1,
                text="second",
                status=CommentStatus.GENERATED,
            )
        )
        await s.commit()

    poster = _FakePoster()
    plugin = CommentingWorkerPlugin(poster=poster)
    did = await plugin.step(_ctx(db_factory))
    assert did is True
    assert poster.calls[0][3] == "first"

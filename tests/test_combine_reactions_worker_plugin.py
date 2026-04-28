"""Unit tests for :class:`ReactionsWorkerPlugin` — full lifecycle with in-memory DB."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sonya.combine.reactions.telethon_poster import TelethonReactionPoster
from sonya.combine.reactions.worker_plugin import ReactionsWorkerPlugin
from sonya.combine.worker.plugin import WorkerContext
from sonya.combine.worker.rate_limit import AccountRateLimiter
from sonya.db.base import Base
from sonya.db.models_combine import (  # noqa: F401 — register tables
    Account,
    AccountRole,
    AccountStatus,
    Owner,
    Proxy,
    ProxyType,
    Reaction,
    ReactionCampaign,
    ReactionCampaignStatus,
    ReactionStatus,
    ReactionTarget,
    ReactionTargetStatus,
)

# ----------------------- fakes -----------------------


class _FloodWaitError(Exception):
    """Fake FloodWaitError with a ``seconds`` attribute."""

    def __init__(self, seconds: int) -> None:
        super().__init__(f"flood wait {seconds}s")
        self.seconds = seconds

    # duck-type: rate_limiter checks type.__name__
    pass


_FloodWaitError.__name__ = "FloodWaitError"


@dataclass
class FakeClient:
    """Mimics a connected TelegramClient."""

    connected: bool = False
    disconnected: bool = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True


class FakePoster(TelethonReactionPoster):
    """Records calls and optionally raises on specific invocations."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any, int, str]] = []
        self._raise_for: dict[int, Exception] = {}

    def raise_on_account(self, account_id: int, exc: Exception) -> None:
        self._raise_for[account_id] = exc

    async def post(
        self,
        client: Any,
        channel: Any,
        tg_message_id: int,
        emoji: str,
    ) -> None:
        self.calls.append((client, channel, tg_message_id, emoji))
        # We identify the account through the emoji→account mapping set up in
        # the test. To simplify, we let the test register errors by account_id
        # but we need the account_id from the caller. We store it on the client.
        account_id = getattr(client, "_test_account_id", None)
        if account_id is not None and account_id in self._raise_for:
            raise self._raise_for.pop(account_id)


@dataclass
class FakeTelethonFactory:
    """Returns pre-built FakeClients keyed by account id."""

    clients: dict[int, FakeClient] = field(default_factory=dict)

    def make_client(self, account: Account, proxy: Proxy | None = None) -> FakeClient:
        client = self.clients.get(account.id, FakeClient())
        # Tag the client so the poster can identify the account.
        client._test_account_id = account.id  # type: ignore[attr-defined]
        return client


# ----------------------- fixtures -----------------------


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    # Seed the default owner.
    async with factory() as s:
        s.add(Owner(id=1, name="default"))
        await s.commit()
    yield factory
    await engine.dispose()


async def _seed_accounts(
    sf: async_sessionmaker[AsyncSession],
    *account_ids: int,
) -> None:
    """Insert minimal Account rows needed by the plugin."""
    async with sf() as s:
        for aid in account_ids:
            s.add(
                Account(
                    id=aid,
                    owner_id=1,
                    phone=f"+100000000{aid:02d}",
                    role=AccountRole.MULTI,
                    status=AccountStatus.ACTIVE,
                    session_blob=b"FAKE_SESSION",
                )
            )
        await s.commit()


async def _seed_target_with_reactions(
    sf: async_sessionmaker[AsyncSession],
    *,
    target_id: int = 1,
    campaign_id: int = 1,
    channel: str = "@news",
    tg_message_id: int = 100,
    reactions: list[tuple[int, str]],
) -> None:
    """Insert campaign + target + pending reactions."""
    async with sf() as s:
        campaign = ReactionCampaign(
            id=campaign_id,
            owner_id=1,
            name="test-campaign",
            status=ReactionCampaignStatus.RUNNING,
            target_channels=[channel],
            account_ids=[r[0] for r in reactions],
            emojis=list({r[1] for r in reactions}),
            accounts_per_post=len(reactions),
            max_reactions_per_day=200,
        )
        s.add(campaign)
        await s.flush()

        target = ReactionTarget(
            id=target_id,
            campaign_id=campaign_id,
            channel=channel,
            tg_message_id=tg_message_id,
            status=ReactionTargetStatus.PLANNED,
            observed_at=datetime.now(timezone.utc),
        )
        s.add(target)
        await s.flush()

        for idx, (account_id, emoji) in enumerate(reactions, start=1):
            s.add(
                Reaction(
                    id=idx,
                    target_id=target_id,
                    account_id=account_id,
                    emoji=emoji,
                    status=ReactionStatus.PENDING,
                )
            )
        await s.commit()


def _make_ctx(
    sf: async_sessionmaker[AsyncSession],
    *,
    telethon_factory: FakeTelethonFactory | None = None,
    rate_limiter: AccountRateLimiter | None = None,
) -> WorkerContext:
    return WorkerContext(
        session_factory=sf,
        telethon_factory=telethon_factory or FakeTelethonFactory(),  # type: ignore[arg-type]
        rate_limiter=rate_limiter or AccountRateLimiter(),
        owner_id=1,
    )


# ----------------------- tests -----------------------


@pytest.mark.asyncio
async def test_step_returns_false_when_nothing_to_do(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    plugin = ReactionsWorkerPlugin()
    ctx = _make_ctx(session_factory)
    assert await plugin.step(ctx) is False


@pytest.mark.asyncio
async def test_happy_path_two_reactions_posted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """PLANNED target with 2 pending reactions → step → 2 POSTED + target DONE."""
    await _seed_accounts(session_factory, 10, 20)
    await _seed_target_with_reactions(
        session_factory,
        reactions=[(10, "\U0001f44d"), (20, "\U0001f525")],
    )

    poster = FakePoster()
    factory = FakeTelethonFactory()
    ctx = _make_ctx(session_factory, telethon_factory=factory)
    plugin = ReactionsWorkerPlugin(poster=poster)

    result = await plugin.step(ctx)
    assert result is True
    assert len(poster.calls) == 2

    # Verify DB state.
    async with session_factory() as s:
        target = await s.get(ReactionTarget, 1)
        assert target is not None
        assert target.status == ReactionTargetStatus.DONE

        r1 = await s.get(Reaction, 1)
        r2 = await s.get(Reaction, 2)
        assert r1 is not None and r1.status == ReactionStatus.POSTED
        assert r1.posted_at is not None
        assert r2 is not None and r2.status == ReactionStatus.POSTED
        assert r2.posted_at is not None


@pytest.mark.asyncio
async def test_flood_wait_keeps_reaction_pending(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FloodWaitError on one reaction → that reaction stays PENDING, other POSTED."""
    await _seed_accounts(session_factory, 10, 20)
    await _seed_target_with_reactions(
        session_factory,
        reactions=[(10, "\U0001f44d"), (20, "\U0001f525")],
    )

    poster = FakePoster()
    poster.raise_on_account(10, _FloodWaitError(seconds=60))

    factory = FakeTelethonFactory()
    limiter = AccountRateLimiter()
    ctx = _make_ctx(session_factory, telethon_factory=factory, rate_limiter=limiter)
    plugin = ReactionsWorkerPlugin(poster=poster)

    result = await plugin.step(ctx)
    assert result is True

    async with session_factory() as s:
        r1 = await s.get(Reaction, 1)
        r2 = await s.get(Reaction, 2)
        assert r1 is not None and r1.status == ReactionStatus.PENDING
        assert r2 is not None and r2.status == ReactionStatus.POSTED

        # Target should NOT be DONE because r1 is still pending.
        target = await s.get(ReactionTarget, 1)
        assert target is not None
        assert target.status == ReactionTargetStatus.PLANNED

    # Flood should be recorded in the rate limiter.
    assert limiter.is_flood_blocked(10)
    assert not limiter.is_flood_blocked(20)


@pytest.mark.asyncio
async def test_generic_error_marks_reaction_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Non-flood error → reaction FAILED with error text, other POSTED."""
    await _seed_accounts(session_factory, 10, 20)
    await _seed_target_with_reactions(
        session_factory,
        reactions=[(10, "\U0001f44d"), (20, "\U0001f525")],
    )

    poster = FakePoster()
    poster.raise_on_account(10, RuntimeError("CHAT_WRITE_FORBIDDEN"))

    factory = FakeTelethonFactory()
    ctx = _make_ctx(session_factory, telethon_factory=factory)
    plugin = ReactionsWorkerPlugin(poster=poster)

    result = await plugin.step(ctx)
    assert result is True

    async with session_factory() as s:
        r1 = await s.get(Reaction, 1)
        r2 = await s.get(Reaction, 2)
        assert r1 is not None and r1.status == ReactionStatus.FAILED
        assert r1.error is not None and "CHAT_WRITE_FORBIDDEN" in r1.error
        assert r2 is not None and r2.status == ReactionStatus.POSTED

        # All reactions terminal → target DONE.
        target = await s.get(ReactionTarget, 1)
        assert target is not None
        assert target.status == ReactionTargetStatus.DONE


@pytest.mark.asyncio
async def test_all_flood_wait_target_stays_planned(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """When every reaction hits FloodWait, target stays PLANNED."""
    await _seed_accounts(session_factory, 10, 20)
    await _seed_target_with_reactions(
        session_factory,
        reactions=[(10, "\U0001f44d"), (20, "\U0001f525")],
    )

    poster = FakePoster()
    poster.raise_on_account(10, _FloodWaitError(seconds=30))
    poster.raise_on_account(20, _FloodWaitError(seconds=30))

    factory = FakeTelethonFactory()
    limiter = AccountRateLimiter()
    ctx = _make_ctx(session_factory, telethon_factory=factory, rate_limiter=limiter)
    plugin = ReactionsWorkerPlugin(poster=poster)

    await plugin.step(ctx)

    async with session_factory() as s:
        target = await s.get(ReactionTarget, 1)
        assert target is not None
        assert target.status == ReactionTargetStatus.PLANNED
        r1 = await s.get(Reaction, 1)
        r2 = await s.get(Reaction, 2)
        assert r1 is not None and r1.status == ReactionStatus.PENDING
        assert r2 is not None and r2.status == ReactionStatus.PENDING


@pytest.mark.asyncio
async def test_step_second_pass_completes_target(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two-step lifecycle: first step floods one reaction, second step posts it → DONE."""
    await _seed_accounts(session_factory, 10, 20)
    await _seed_target_with_reactions(
        session_factory,
        reactions=[(10, "\U0001f44d"), (20, "\U0001f525")],
    )

    poster = FakePoster()
    poster.raise_on_account(10, _FloodWaitError(seconds=0))

    factory = FakeTelethonFactory()
    # Use a no-wait limiter so the second step doesn't actually sleep.
    limiter = AccountRateLimiter()
    ctx = _make_ctx(session_factory, telethon_factory=factory, rate_limiter=limiter)
    plugin = ReactionsWorkerPlugin(poster=poster)

    # First step: account 10 floods, account 20 posts.
    await plugin.step(ctx)

    async with session_factory() as s:
        r1 = await s.get(Reaction, 1)
        assert r1 is not None and r1.status == ReactionStatus.PENDING

    # Second step: account 10 succeeds now (no more raise registered).
    result = await plugin.step(ctx)
    assert result is True

    async with session_factory() as s:
        r1 = await s.get(Reaction, 1)
        assert r1 is not None and r1.status == ReactionStatus.POSTED
        target = await s.get(ReactionTarget, 1)
        assert target is not None
        assert target.status == ReactionTargetStatus.DONE


@pytest.mark.asyncio
async def test_plugin_name_attribute() -> None:
    plugin = ReactionsWorkerPlugin()
    assert plugin.name == "reactions"


@pytest.mark.asyncio
async def test_missing_account_marks_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Reaction referencing a non-existent account → FAILED."""
    # Do NOT seed account 99 — it should be missing.
    await _seed_target_with_reactions(
        session_factory,
        reactions=[(99, "\U0001f44d")],
    )

    poster = FakePoster()
    ctx = _make_ctx(session_factory, telethon_factory=FakeTelethonFactory())
    plugin = ReactionsWorkerPlugin(poster=poster)

    result = await plugin.step(ctx)
    assert result is True

    async with session_factory() as s:
        r1 = await s.get(Reaction, 1)
        assert r1 is not None and r1.status == ReactionStatus.FAILED
        assert r1.error is not None and "not found" in r1.error
        target = await s.get(ReactionTarget, 1)
        assert target is not None
        assert target.status == ReactionTargetStatus.DONE

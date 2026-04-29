"""Unit tests for :class:`ParserWorkerPlugin` with in-memory SQLite."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sonya.combine.parsers.worker_plugin import ParserWorkerPlugin
from sonya.combine.worker.plugin import WorkerContext
from sonya.combine.worker.rate_limit import AccountRateLimiter, FloodWaitError
from sonya.db.base import Base
from sonya.db.models_combine import (
    Account,
    AccountRole,
    AccountStatus,
    Owner,
    ParserJob,
    ParserJobStatus,
    ParserKind,
    ParserResult,
    ParserResultKind,
    Proxy,
    ProxyType,
)

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_factory(
    db_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Pre-seeds Owner, Account, Proxy, and a pending ParserJob."""
    async with db_factory() as session:
        session.add(Owner(id=1, name="default"))
        await session.flush()

        proxy = Proxy(
            id=1,
            owner_id=1,
            type=ProxyType.SOCKS5,
            host="p.example.com",
            port=1080,
        )
        session.add(proxy)
        await session.flush()

        acc = Account(
            id=1,
            owner_id=1,
            phone="+10000000001",
            role=AccountRole.PARSER,
            status=AccountStatus.ACTIVE,
            proxy_id=1,
            session_blob=b"FAKE_SESSION",
            api_id=123,
            api_hash="abc",
        )
        session.add(acc)
        await session.flush()

        job = ParserJob(
            id=1,
            owner_id=1,
            account_id=1,
            kind=ParserKind.USERS_IN_CHAT,
            target="test_chat",
            params={},
            status=ParserJobStatus.PENDING,
            result_count=0,
        )
        session.add(job)
        await session.commit()
    yield db_factory


# ------------------------------------------------------------------
# Fake client + factory
# ------------------------------------------------------------------


class FakeUser:
    def __init__(
        self, *, id: int, username: str | None = None, first_name: str | None = None
    ) -> None:
        self.id = id
        self.username = username
        self.first_name = first_name
        self.last_name = None


class FakeTelegramClient:
    def __init__(
        self, *, participants: list[Any] | None = None, error: Exception | None = None
    ) -> None:
        self._participants = participants or []
        self._error = error
        self.connected = False
        self.disconnected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def iter_participants(self, chat: Any) -> Any:  # noqa: ANN401
        if self._error is not None:
            raise self._error
        for u in self._participants:
            yield u

    async def iter_dialogs(self) -> Any:  # noqa: ANN401
        return
        yield  # pragma: no cover

    async def iter_messages(self, peer: Any, *, limit: int = 100, search: str = "") -> Any:  # noqa: ANN401
        return
        yield  # pragma: no cover


class FakeTelethonClientFactory:
    def __init__(self, client: FakeTelegramClient) -> None:
        self._client = client

    def make_client(self, account: Account, proxy: Any = None) -> FakeTelegramClient:
        return self._client


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_success(seeded_factory: async_sessionmaker[AsyncSession]) -> None:
    users = [
        FakeUser(id=100, username="alice", first_name="Alice"),
        FakeUser(id=101, username="bob", first_name="Bob"),
    ]
    fake_client = FakeTelegramClient(participants=users)
    factory = FakeTelethonClientFactory(fake_client)
    rate_limiter = AccountRateLimiter()
    ctx = WorkerContext(
        session_factory=seeded_factory,
        telethon_factory=factory,  # type: ignore[arg-type]
        rate_limiter=rate_limiter,
        owner_id=1,
    )

    plugin = ParserWorkerPlugin()
    did_work = await plugin.step(ctx)
    assert did_work is True
    assert fake_client.connected is True
    assert fake_client.disconnected is True

    # Verify job is completed and results are stored.
    async with seeded_factory() as session:
        job = await session.get(ParserJob, 1)
        assert job is not None
        assert job.status == ParserJobStatus.COMPLETED
        assert job.result_count == 2
        assert job.error is None

        from sqlalchemy import select

        rows = list(
            (await session.execute(select(ParserResult).where(ParserResult.job_id == 1))).scalars()
        )
        assert len(rows) == 2
        assert all(r.kind == ParserResultKind.USER for r in rows)


@pytest.mark.asyncio
async def test_step_no_pending_jobs(db_factory: async_sessionmaker[AsyncSession]) -> None:
    """When there are no pending jobs, step returns False."""
    async with db_factory() as session:
        session.add(Owner(id=1, name="default"))
        await session.commit()

    fake_client = FakeTelegramClient()
    factory = FakeTelethonClientFactory(fake_client)
    rate_limiter = AccountRateLimiter()
    ctx = WorkerContext(
        session_factory=db_factory,
        telethon_factory=factory,  # type: ignore[arg-type]
        rate_limiter=rate_limiter,
        owner_id=1,
    )

    plugin = ParserWorkerPlugin()
    assert await plugin.step(ctx) is False


@pytest.mark.asyncio
async def test_step_failure_marks_job_failed(
    seeded_factory: async_sessionmaker[AsyncSession],
) -> None:
    """When the client raises, the job is marked FAILED."""
    error = RuntimeError("Telegram API error")
    fake_client = FakeTelegramClient(error=error)
    factory = FakeTelethonClientFactory(fake_client)
    rate_limiter = AccountRateLimiter()
    ctx = WorkerContext(
        session_factory=seeded_factory,
        telethon_factory=factory,  # type: ignore[arg-type]
        rate_limiter=rate_limiter,
        owner_id=1,
    )

    plugin = ParserWorkerPlugin()
    did_work = await plugin.step(ctx)
    assert did_work is True

    async with seeded_factory() as session:
        job = await session.get(ParserJob, 1)
        assert job is not None
        assert job.status == ParserJobStatus.FAILED
        assert job.error is not None
        assert "Telegram API error" in job.error


@pytest.mark.asyncio
async def test_step_flood_wait_reverts_to_pending(
    seeded_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FloodWaitError records back-off and reverts job to PENDING."""
    flood_error = FloodWaitError(seconds=60)
    fake_client = FakeTelegramClient(error=flood_error)
    factory = FakeTelethonClientFactory(fake_client)
    rate_limiter = AccountRateLimiter()
    ctx = WorkerContext(
        session_factory=seeded_factory,
        telethon_factory=factory,  # type: ignore[arg-type]
        rate_limiter=rate_limiter,
        owner_id=1,
    )

    plugin = ParserWorkerPlugin()
    did_work = await plugin.step(ctx)
    assert did_work is True

    async with seeded_factory() as session:
        job = await session.get(ParserJob, 1)
        assert job is not None
        assert job.status == ParserJobStatus.PENDING

    # Rate limiter should have recorded the flood.
    assert rate_limiter.is_flood_blocked(1) is True

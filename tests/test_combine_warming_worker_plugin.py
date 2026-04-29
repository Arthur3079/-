"""Unit tests for :class:`WarmingWorkerPlugin` — full lifecycle on SQLite."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sonya.combine.warming.telethon_executor import TelethonWarmingExecutor
from sonya.combine.warming.worker_plugin import WarmingWorkerPlugin
from sonya.combine.worker.plugin import WorkerContext
from sonya.combine.worker.rate_limit import AccountRateLimiter
from sonya.db.base import Base
from sonya.db.models_combine import (
    Account,
    AccountRole,
    AccountStatus,
    Owner,
    Proxy,
    WarmingAction,
    WarmingActionKind,
    WarmingActionStatus,
    WarmingJob,
    WarmingJobStatus,
)

# --------------- fakes ---------------


class _FakeFloodWaitError(Exception):
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


class _RecordingExecutor(TelethonWarmingExecutor):
    """Replaces real Telethon calls with a recorder + optional raise."""

    def __init__(self) -> None:
        super().__init__()
        self.executed: list[tuple[int, WarmingActionKind]] = []
        self._raise_for: dict[int, Exception] = {}

    def raise_on_account(self, account_id: int, exc: Exception) -> None:
        self._raise_for[account_id] = exc

    async def execute(self, client: Any, action: WarmingAction) -> None:
        account_id = getattr(client, "account_id", None)
        self.executed.append((action.id, action.kind))
        if account_id is not None and account_id in self._raise_for:
            raise self._raise_for.pop(account_id)


@dataclass
class _FakeFactory:
    clients: dict[int, _FakeClient] = field(default_factory=dict)

    def make_client(self, account: Account, proxy: Proxy | None = None) -> _FakeClient:
        client = self.clients.get(account.id, _FakeClient())
        client.account_id = account.id
        return client


# --------------- fixtures ---------------


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


async def _seed_job(
    sf: async_sessionmaker[AsyncSession],
    *,
    job_status: WarmingJobStatus = WarmingJobStatus.PENDING,
    actions: list[tuple[WarmingActionKind, str | None, int]] | None = None,
    account_id: int = 1,
    account_status: AccountStatus = AccountStatus.NEW,
    trust_score: int = 10,
    target_trust_score: int = 50,
    scheduled_offset_seconds: int = -10,
) -> tuple[int, list[int]]:
    """Insert one Account + WarmingJob with the listed actions.

    Returns ``(job_id, [action_ids])``.
    """
    actions = actions or [(WarmingActionKind.SEND_IDLE_MESSAGE, None, 1)]
    async with sf() as s:
        s.add(
            Account(
                id=account_id,
                owner_id=1,
                phone=f"+100000000{account_id:02d}",
                role=AccountRole.MULTI,
                status=account_status,
                session_blob=b"FAKE_SESSION",
                trust_score=trust_score,
            )
        )
        job = WarmingJob(
            id=1,
            owner_id=1,
            account_id=account_id,
            status=job_status,
            target_trust_score=target_trust_score,
        )
        s.add(job)
        await s.flush()
        scheduled = datetime.now(timezone.utc) + timedelta(seconds=scheduled_offset_seconds)
        action_ids: list[int] = []
        for kind, target, delta in actions:
            a = WarmingAction(
                job_id=job.id,
                kind=kind,
                target=target,
                scheduled_at=scheduled,
                status=WarmingActionStatus.PENDING,
                trust_delta=delta,
            )
            s.add(a)
            await s.flush()
            action_ids.append(a.id)
        await s.commit()
        return job.id, action_ids


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


# --------------- tests ---------------


@pytest.mark.asyncio
async def test_step_no_work(db_factory: async_sessionmaker[AsyncSession]) -> None:
    plugin = WarmingWorkerPlugin(executor=_RecordingExecutor())
    assert await plugin.step(_ctx(db_factory)) is False


@pytest.mark.asyncio
async def test_step_success_marks_done_and_bumps_trust(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id, [aid] = await _seed_job(
        db_factory,
        actions=[(WarmingActionKind.SEND_IDLE_MESSAGE, None, 5)],
        trust_score=10,
    )
    exe = _RecordingExecutor()
    plugin = WarmingWorkerPlugin(executor=exe)

    assert await plugin.step(_ctx(db_factory)) is True

    async with db_factory() as s:
        action = await s.get(WarmingAction, aid)
        job = await s.get(WarmingJob, job_id)
        account = await s.get(Account, 1)
        assert action is not None and job is not None and account is not None
        assert action.status == WarmingActionStatus.DONE
        assert action.executed_at is not None
        assert action.error is None
        # Single-action job → status flips RUNNING then COMPLETED.
        assert job.status == WarmingJobStatus.COMPLETED
        assert job.completed_at is not None
        assert account.trust_score == 15
        # Account was NEW, trust < target_trust_score=50, so status flips to WARMING.
        assert account.status == AccountStatus.WARMING

    assert exe.executed == [(aid, WarmingActionKind.SEND_IDLE_MESSAGE)]


@pytest.mark.asyncio
async def test_step_skips_paused_job(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_job(db_factory, job_status=WarmingJobStatus.PAUSED)
    plugin = WarmingWorkerPlugin(executor=_RecordingExecutor())
    assert await plugin.step(_ctx(db_factory)) is False


@pytest.mark.asyncio
async def test_step_skips_future_action(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_job(db_factory, scheduled_offset_seconds=3600)
    plugin = WarmingWorkerPlugin(executor=_RecordingExecutor())
    assert await plugin.step(_ctx(db_factory)) is False


@pytest.mark.asyncio
async def test_step_flood_wait_keeps_action_pending(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, [aid] = await _seed_job(db_factory)
    exe = _RecordingExecutor()
    exe.raise_on_account(1, _FakeFloodWaitError(seconds=33))
    rl = AccountRateLimiter()
    plugin = WarmingWorkerPlugin(executor=exe)

    assert await plugin.step(_ctx(db_factory, rate_limiter=rl)) is True

    async with db_factory() as s:
        action = await s.get(WarmingAction, aid)
        assert action is not None
        assert action.status == WarmingActionStatus.PENDING
        assert action.error is None
    assert rl.is_flood_blocked(1) is True


@pytest.mark.asyncio
async def test_step_failure_marks_failed(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, [aid] = await _seed_job(db_factory)
    exe = _RecordingExecutor()
    exe.raise_on_account(1, RuntimeError("nope"))
    plugin = WarmingWorkerPlugin(executor=exe)

    assert await plugin.step(_ctx(db_factory)) is True

    async with db_factory() as s:
        action = await s.get(WarmingAction, aid)
        account = await s.get(Account, 1)
        assert action is not None and account is not None
        assert action.status == WarmingActionStatus.FAILED
        assert action.error is not None and "nope" in action.error
        # Trust must NOT bump on failure.
        assert account.trust_score == 10


@pytest.mark.asyncio
async def test_step_picks_earliest_scheduled_first(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two due actions on different jobs — the earlier scheduled one wins."""
    # First job (later schedule)
    async with db_factory() as s:
        s.add(
            Account(
                id=1,
                owner_id=1,
                phone="+10000000001",
                role=AccountRole.MULTI,
                status=AccountStatus.ACTIVE,
                session_blob=b"FAKE",
                trust_score=10,
            )
        )
        job1 = WarmingJob(id=1, owner_id=1, account_id=1, status=WarmingJobStatus.PENDING)
        s.add(job1)
        await s.flush()
        a_late = WarmingAction(
            job_id=job1.id,
            kind=WarmingActionKind.SEND_IDLE_MESSAGE,
            scheduled_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            status=WarmingActionStatus.PENDING,
            trust_delta=1,
        )
        a_early = WarmingAction(
            job_id=job1.id,
            kind=WarmingActionKind.SEND_IDLE_MESSAGE,
            scheduled_at=datetime.now(timezone.utc) - timedelta(seconds=120),
            status=WarmingActionStatus.PENDING,
            trust_delta=1,
        )
        s.add_all([a_late, a_early])
        await s.commit()
        early_id = a_early.id

    exe = _RecordingExecutor()
    plugin = WarmingWorkerPlugin(executor=exe)
    assert await plugin.step(_ctx(db_factory)) is True
    assert exe.executed[0][0] == early_id


@pytest.mark.asyncio
async def test_step_completes_multi_action_job_only_when_all_terminal(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id, [a1, a2] = await _seed_job(
        db_factory,
        actions=[
            (WarmingActionKind.SEND_IDLE_MESSAGE, None, 1),
            (WarmingActionKind.SEND_IDLE_MESSAGE, None, 1),
        ],
    )
    plugin = WarmingWorkerPlugin(executor=_RecordingExecutor())

    # First step → first action done, job RUNNING but not COMPLETED.
    assert await plugin.step(_ctx(db_factory)) is True
    async with db_factory() as s:
        job = await s.get(WarmingJob, job_id)
        assert job is not None
        assert job.status == WarmingJobStatus.RUNNING
        assert job.completed_at is None

    # Second step → second action done, job flips COMPLETED.
    assert await plugin.step(_ctx(db_factory)) is True
    async with db_factory() as s:
        job = await s.get(WarmingJob, job_id)
        assert job is not None
        assert job.status == WarmingJobStatus.COMPLETED
        assert job.completed_at is not None
    del a1, a2

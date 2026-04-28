"""Unit tests for ``AccountRateLimiter``."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from sonya.combine.worker.rate_limit import AccountRateLimiter, FloodWaitError


class _FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _FakeSleep:
    def __init__(self, clock: _FakeClock) -> None:
        self.clock = clock
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        # Advance the fake clock so subsequent flood checks see no remainder.
        self.clock.tick(seconds)


def test_constructor_rejects_zero_concurrency() -> None:
    with pytest.raises(ValueError):
        AccountRateLimiter(max_concurrent_per_account=0)


@pytest.mark.asyncio
async def test_acquire_serialises_per_account() -> None:
    limiter = AccountRateLimiter(max_concurrent_per_account=1)

    in_flight = 0
    max_in_flight = 0
    enter_count = 0

    async def task() -> None:
        nonlocal in_flight, max_in_flight, enter_count
        async with limiter.acquire(account_id=1):
            in_flight += 1
            enter_count += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1

    await asyncio.gather(*(task() for _ in range(5)))
    assert enter_count == 5
    assert max_in_flight == 1


@pytest.mark.asyncio
async def test_acquire_does_not_serialise_across_accounts() -> None:
    limiter = AccountRateLimiter(max_concurrent_per_account=1)

    in_flight = 0
    max_in_flight = 0

    async def task(account_id: int) -> None:
        nonlocal in_flight, max_in_flight
        async with limiter.acquire(account_id=account_id):
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.02)
            in_flight -= 1

    await asyncio.gather(task(1), task(2), task(3))
    assert max_in_flight == 3


@pytest.mark.asyncio
async def test_higher_concurrency_allowed_per_account() -> None:
    limiter = AccountRateLimiter(max_concurrent_per_account=3)

    in_flight = 0
    max_in_flight = 0

    async def task() -> None:
        nonlocal in_flight, max_in_flight
        async with limiter.acquire(account_id=1):
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.02)
            in_flight -= 1

    await asyncio.gather(*(task() for _ in range(10)))
    assert max_in_flight == 3


# ----------------------- flood wait -----------------------


@pytest.mark.asyncio
async def test_record_flood_wait_blocks_acquire_until_deadline() -> None:
    clock = _FakeClock()
    sleep = _FakeSleep(clock)
    limiter = AccountRateLimiter(clock=clock, sleep=sleep)

    limiter.record_flood_wait(account_id=42, seconds=60)
    assert limiter.is_flood_blocked(42)
    assert limiter.flood_remaining_seconds(42) == pytest.approx(60.0)

    async with limiter.acquire(account_id=42):
        pass

    assert sleep.calls == [pytest.approx(60.0)]
    assert not limiter.is_flood_blocked(42)


@pytest.mark.asyncio
async def test_flood_wait_extends_when_longer_received() -> None:
    clock = _FakeClock()
    sleep = _FakeSleep(clock)
    limiter = AccountRateLimiter(clock=clock, sleep=sleep)

    limiter.record_flood_wait(account_id=1, seconds=10)
    limiter.record_flood_wait(account_id=1, seconds=120)
    # Shorter follow-up should not shorten the existing back-off.
    limiter.record_flood_wait(account_id=1, seconds=5)

    assert limiter.flood_remaining_seconds(1) == pytest.approx(120.0)


@pytest.mark.asyncio
async def test_flood_wait_already_elapsed_skips_sleep() -> None:
    clock = _FakeClock()
    sleep = _FakeSleep(clock)
    limiter = AccountRateLimiter(clock=clock, sleep=sleep)

    limiter.record_flood_wait(account_id=7, seconds=30)
    clock.tick(31)
    assert not limiter.is_flood_blocked(7)

    async with limiter.acquire(account_id=7):
        pass
    assert sleep.calls == []


@pytest.mark.asyncio
async def test_flood_wait_recorded_inside_critical_section_blocks_queued_task() -> None:
    """Regression: Task B was queued on the semaphore at the moment Task A,
    just before releasing the semaphore, recorded a FloodWait. Task B must
    re-observe that flood and back off — *not* proceed straight through.

    Before the fix the flood check happened *before* `async with sem`, so
    Task B's check ran while no flood was active, then it blocked on the
    semaphore, and finally proceeded without honouring the freshly-recorded
    flood.
    """

    clock = _FakeClock()
    sleep = _FakeSleep(clock)
    limiter = AccountRateLimiter(clock=clock, sleep=sleep)

    started_inside = asyncio.Event()
    release_a = asyncio.Event()

    async def task_a() -> None:
        async with limiter.acquire(account_id=1):
            started_inside.set()
            await release_a.wait()
            limiter.record_flood_wait(1, 60)

    async def task_b() -> None:
        # Wait until A is inside the semaphore so B is guaranteed to block.
        await started_inside.wait()
        async with limiter.acquire(account_id=1):
            pass

    a = asyncio.create_task(task_a())
    b = asyncio.create_task(task_b())

    # Let A start, queue B on the semaphore, then release A.
    await started_inside.wait()
    await asyncio.sleep(0)  # let B reach `async with limiter.acquire`
    release_a.set()

    await asyncio.gather(a, b)

    # B must have slept the full 60s back-off recorded by A.
    assert sleep.calls == [pytest.approx(60.0)]


def test_record_flood_wait_ignores_non_positive() -> None:
    limiter = AccountRateLimiter()
    limiter.record_flood_wait(account_id=1, seconds=0)
    limiter.record_flood_wait(account_id=1, seconds=-5)
    assert not limiter.is_flood_blocked(1)


def test_flood_wait_error_carries_seconds() -> None:
    err = FloodWaitError(seconds=42)
    assert err.seconds == 42
    assert "42s" in str(err)

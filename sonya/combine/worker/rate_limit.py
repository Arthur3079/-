"""Per-account rate limiting + FloodWait back-off for the worker.

Every Telethon call a plugin makes should go through
:meth:`AccountRateLimiter.acquire` (an async context manager) so that:

1. Only ``max_concurrent_per_account`` tasks run for the same account
   at the same time. With the default of 1 this serialises all work
   under a given account — Telethon's own session is single-threaded
   anyway and FloodWait risk grows quickly with concurrency.
2. If a previous call hit a ``FloodWaitError``, every subsequent call
   under that account waits until the back-off elapses.

The limiter does *not* know about Telethon directly — plugins are
responsible for catching ``FloodWaitError`` and calling
:meth:`record_flood_wait` so future ticks observe the back-off.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone


class FloodWaitError(RuntimeError):
    """Internal error mirroring ``telethon.errors.FloodWaitError``.

    Plugins can re-raise Telethon's exception unchanged — the limiter
    only checks ``isinstance(..., FloodWaitError)`` (or duck-typing on
    a ``seconds`` attribute) so both work.
    """

    def __init__(self, seconds: int) -> None:
        super().__init__(f"flood wait {seconds}s")
        self.seconds = int(seconds)


class AccountRateLimiter:
    """Per-account semaphore + flood back-off.

    The limiter is fully in-memory; restarting the worker resets all
    flood records. That's fine — the durable state lives on the
    ``Account`` row (``flood_until``) and the next claim cycle picks
    it up from there.
    """

    def __init__(
        self,
        *,
        max_concurrent_per_account: int = 1,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], asyncio.Future[None] | object] | None = None,
    ) -> None:
        if max_concurrent_per_account < 1:
            raise ValueError("max_concurrent_per_account must be >= 1")
        self._max = max_concurrent_per_account
        self._semaphores: dict[int, asyncio.Semaphore] = {}
        self._floods: dict[int, datetime] = {}
        self._init_lock = asyncio.Lock()
        # ``clock`` is injected so tests don't have to wait real seconds.
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # ``sleep`` is injected for the same reason. Default is asyncio.sleep.
        self._sleep = sleep or asyncio.sleep

    def _semaphore_for(self, account_id: int) -> asyncio.Semaphore:
        sem = self._semaphores.get(account_id)
        if sem is None:
            sem = asyncio.Semaphore(self._max)
            self._semaphores[account_id] = sem
        return sem

    async def _wait_out_flood(self, account_id: int) -> None:
        deadline = self._floods.get(account_id)
        if deadline is None:
            return
        remaining = (deadline - self._clock()).total_seconds()
        if remaining <= 0:
            self._floods.pop(account_id, None)
            return
        await self._sleep(remaining)
        self._floods.pop(account_id, None)

    @asynccontextmanager
    async def acquire(self, account_id: int) -> AsyncIterator[None]:
        """Wait for the per-account slot, honouring any active flood back-off.

        Usage::

            async with rate_limiter.acquire(account.id):
                try:
                    await client.send_message(...)
                except telethon.errors.FloodWaitError as e:
                    rate_limiter.record_flood_wait(account.id, e.seconds)
                    raise
        """

        # Construct semaphores under a lock so two concurrent first-touches
        # for the same account don't end up with separate Semaphore objects.
        async with self._init_lock:
            sem = self._semaphore_for(account_id)

        # Flood check MUST run inside the semaphore so a task that's been
        # queueing on the semaphore re-observes any flood that the previous
        # holder recorded just before releasing. Otherwise Task B can pass
        # the flood check while no flood is active, block on the semaphore
        # while Task A records a flood, and then proceed without backing off.
        async with sem:
            await self._wait_out_flood(account_id)
            yield

    def record_flood_wait(self, account_id: int, seconds: int) -> None:
        """Remember a FloodWait so future :meth:`acquire` calls back off."""
        if seconds <= 0:
            return
        deadline = self._clock() + timedelta(seconds=int(seconds))
        # Always extend the longer of the two — we'd rather over-wait than
        # spam Telegram into a longer ban.
        existing = self._floods.get(account_id)
        if existing is None or deadline > existing:
            self._floods[account_id] = deadline

    def is_flood_blocked(self, account_id: int) -> bool:
        deadline = self._floods.get(account_id)
        return deadline is not None and deadline > self._clock()

    def flood_remaining_seconds(self, account_id: int) -> float:
        deadline = self._floods.get(account_id)
        if deadline is None:
            return 0.0
        return max(0.0, (deadline - self._clock()).total_seconds())


__all__ = ["AccountRateLimiter", "FloodWaitError"]

"""Per-fan async lock + simple debounce for collapsing message bursts.

Two distinct concerns, both keyed by `fan_id`:

1. `PerFanLockRegistry` — guarantees that only one DialogueService run for a
   given fan is in-flight at a time. Without it, two PMs from the same fan
   arriving close together would each spin up an independent LLM call and we'd
   send two unrelated replies (and waste tokens).

2. `Debouncer.wait_for_quiet` — when a fan sends 3 short messages in a row,
   we want to answer once after the burst settles, not three times. Each new
   incoming message extends the quiet window. The first coroutine to finish
   waiting is the one that proceeds; others should re-check and bail out if
   their message is no longer the latest.

Both are intentionally minimal — no Redis, no broker, single-process only.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class PerFanLockRegistry:
    """Lazy registry of `asyncio.Lock` per `fan_id`.

    Locks are created on first use and never evicted. For a Telethon userbot
    with at most a few thousand active fans this is fine memory-wise.
    """

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def get(self, fan_id: int) -> asyncio.Lock:
        return self._locks[fan_id]

    @asynccontextmanager
    async def hold(self, fan_id: int) -> AsyncIterator[None]:
        """`async with registry.hold(fan_id):` — serialises work for that fan."""
        lock = self.get(fan_id)
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()


class Debouncer:
    """Collapse a burst of incoming messages from the same fan into one trigger.

    Usage:

        debouncer = Debouncer(quiet_period=3.0)
        debouncer.bump(fan_id)  # call on every incoming
        is_latest = await debouncer.wait_for_quiet(fan_id)
        if not is_latest:
            return  # a newer message came in, this coroutine bails
        ... proceed to build & send reply ...
    """

    def __init__(self, quiet_period: float) -> None:
        self._quiet_period = quiet_period
        self._counters: dict[int, int] = defaultdict(int)

    @property
    def quiet_period(self) -> float:
        return self._quiet_period

    def bump(self, fan_id: int) -> int:
        """Mark a new incoming message; returns the new generation number."""
        self._counters[fan_id] += 1
        return self._counters[fan_id]

    def current_generation(self, fan_id: int) -> int:
        return self._counters[fan_id]

    async def wait_for_quiet(self, fan_id: int, generation: int) -> bool:
        """Sleep `quiet_period`. Return True if `generation` is still the latest.

        If a newer `bump(fan_id)` happened during the sleep, returns False —
        caller should drop this work and let the newer coroutine handle it.
        """
        await asyncio.sleep(self._quiet_period)
        return self._counters[fan_id] == generation

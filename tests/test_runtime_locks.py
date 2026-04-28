"""Tests for PerFanLockRegistry and Debouncer."""

from __future__ import annotations

import asyncio

from sonya.runtime.locks import Debouncer, PerFanLockRegistry


async def test_lock_serialises_same_fan() -> None:
    locks = PerFanLockRegistry()
    order: list[str] = []

    async def worker(label: str) -> None:
        async with locks.hold(fan_id=1):
            order.append(f"{label}:in")
            await asyncio.sleep(0.05)
            order.append(f"{label}:out")

    # Two workers for the SAME fan must not interleave.
    await asyncio.gather(worker("a"), worker("b"))

    assert order in (
        ["a:in", "a:out", "b:in", "b:out"],
        ["b:in", "b:out", "a:in", "a:out"],
    )


async def test_lock_does_not_serialise_different_fans() -> None:
    locks = PerFanLockRegistry()
    order: list[str] = []

    async def worker(fan_id: int, label: str) -> None:
        async with locks.hold(fan_id=fan_id):
            order.append(f"{label}:in")
            await asyncio.sleep(0.05)
            order.append(f"{label}:out")

    await asyncio.gather(worker(1, "a"), worker(2, "b"))
    # Different fans should run in parallel: starts before any out.
    assert order[0].endswith(":in")
    assert order[1].endswith(":in")


async def test_debouncer_collapses_burst() -> None:
    deb = Debouncer(quiet_period=0.05)

    # Three quick "messages" from fan 1.
    g1 = deb.bump(1)
    g2 = deb.bump(1)
    g3 = deb.bump(1)
    assert (g1, g2, g3) == (1, 2, 3)

    # Only the latest generation should "win" the wait.
    won = await deb.wait_for_quiet(1, generation=g3)
    assert won is True

    # An older-generation waiter loses.
    deb._counters[1] = 5  # simulate even more bumps
    assert await deb.wait_for_quiet(1, generation=g3) is False


async def test_debouncer_independent_per_fan() -> None:
    deb = Debouncer(quiet_period=0.02)
    g_a = deb.bump(1)
    g_b = deb.bump(2)
    # Bumps to fan 2 must not invalidate fan 1's waiter.
    deb.bump(2)
    deb.bump(2)
    assert await deb.wait_for_quiet(1, generation=g_a) is True
    assert await deb.wait_for_quiet(2, generation=g_b) is False

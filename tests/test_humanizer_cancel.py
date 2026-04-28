"""Tests for cooperative humanizer cancellation."""

from __future__ import annotations

import asyncio
import time

from sonya.humanizer import (
    HumanizerTiming,
    interruptible_sleep,
    sleep_awareness_interruptible,
    sleep_typing_interruptible,
)


async def test_completes_when_no_cancel() -> None:
    start = time.monotonic()
    ok = await interruptible_sleep(0.05)
    assert ok is True
    assert time.monotonic() - start >= 0.04


async def test_completes_when_cancel_always_false() -> None:
    ok = await interruptible_sleep(0.05, cancel=lambda: False, poll=0.01)
    assert ok is True


async def test_cancels_when_predicate_true() -> None:
    flag = {"v": False}

    def cancel() -> bool:
        return flag["v"]

    async def trip_after(delay: float) -> None:
        await asyncio.sleep(delay)
        flag["v"] = True

    start = time.monotonic()
    sleep_task = asyncio.create_task(interruptible_sleep(2.0, cancel=cancel, poll=0.05))
    asyncio.create_task(trip_after(0.1))
    ok = await sleep_task
    elapsed = time.monotonic() - start
    assert ok is False
    assert elapsed < 1.0  # bailed early


async def test_zero_seconds_returns_immediately() -> None:
    ok = await interruptible_sleep(0.0)
    assert ok is True


async def test_zero_seconds_with_cancel_already_true() -> None:
    ok = await interruptible_sleep(0.0, cancel=lambda: True)
    assert ok is False


async def test_awareness_wrapper_propagates_cancel() -> None:
    timing = HumanizerTiming(awareness_delay=1.0, typing_delay=0.0)
    ok = await sleep_awareness_interruptible(timing, cancel=lambda: True)
    assert ok is False


async def test_typing_wrapper_propagates_cancel() -> None:
    timing = HumanizerTiming(awareness_delay=0.0, typing_delay=1.0)
    ok = await sleep_typing_interruptible(timing, cancel=lambda: True)
    assert ok is False

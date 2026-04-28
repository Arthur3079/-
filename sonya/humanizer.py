"""Базовый «очеловечиватель» исходящих ответов.

MVP-1 делает только две вещи: задержку «осознания» перед typing-индикатором
и задержку «набора» пропорциональную длине текста. Дальше в MVP-3 это
расширится на онлайн-расписание, разбивку на bubbles, mark-as-read и т.п.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from dataclasses import dataclass

# How often we wake up to re-check a cancellation predicate during a long
# humanizer sleep. 200ms is small enough to feel responsive when a fan sends
# a follow-up while we're "typing", and big enough not to hammer the loop.
CANCEL_POLL_INTERVAL_S = 0.2


@dataclass(frozen=True)
class HumanizerTiming:
    awareness_delay: float
    typing_delay: float

    @property
    def total(self) -> float:
        return self.awareness_delay + self.typing_delay


# Скорость печати взрослого пользователя смартфона: ~3-5 символов/сек.
CHARS_PER_SECOND_MIN = 3.0
CHARS_PER_SECOND_MAX = 5.0
AWARENESS_MIN_S = 1.0
AWARENESS_MAX_S = 3.0
TYPING_MIN_S = 0.8
TYPING_MAX_S = 12.0


def calculate_timing(reply_text: str, *, rng: random.Random | None = None) -> HumanizerTiming:
    """Прикинуть, сколько секунд «думает» и «печатает» живой человек.

    `awareness_delay` — задержка ДО включения typing-индикатора (читает входящее).
    `typing_delay`    — собственно время typing-индикатора, до отправки.
    """
    rnd = rng or random
    awareness = rnd.uniform(AWARENESS_MIN_S, AWARENESS_MAX_S)

    chars = max(1, len(reply_text))
    cps = rnd.uniform(CHARS_PER_SECOND_MIN, CHARS_PER_SECOND_MAX)
    typing = chars / cps
    typing = max(TYPING_MIN_S, min(TYPING_MAX_S, typing))

    return HumanizerTiming(awareness_delay=awareness, typing_delay=typing)


async def sleep_awareness(timing: HumanizerTiming) -> None:
    await asyncio.sleep(timing.awareness_delay)


async def sleep_typing(timing: HumanizerTiming) -> None:
    await asyncio.sleep(timing.typing_delay)


async def interruptible_sleep(
    seconds: float,
    *,
    cancel: Callable[[], bool] | None = None,
    poll: float = CANCEL_POLL_INTERVAL_S,
) -> bool:
    """Sleep up to `seconds`, polling `cancel()` every `poll` s.

    Returns True if the full sleep elapsed; False if `cancel()` returned True
    at any point, in which case the caller should bail out (a newer message
    arrived, the operator paused the bot, etc.).
    """
    if seconds <= 0:
        return cancel is None or not cancel()
    if cancel is None:
        await asyncio.sleep(seconds)
        return True
    deadline_steps = max(1, int(seconds / poll))
    remaining = seconds
    for _ in range(deadline_steps):
        if cancel():
            return False
        chunk = min(poll, remaining)
        if chunk <= 0:
            break
        await asyncio.sleep(chunk)
        remaining -= chunk
    if remaining > 0:
        if cancel():
            return False
        await asyncio.sleep(remaining)
    return not cancel()


async def sleep_awareness_interruptible(
    timing: HumanizerTiming, *, cancel: Callable[[], bool] | None = None
) -> bool:
    return await interruptible_sleep(timing.awareness_delay, cancel=cancel)


async def sleep_typing_interruptible(
    timing: HumanizerTiming, *, cancel: Callable[[], bool] | None = None
) -> bool:
    return await interruptible_sleep(timing.typing_delay, cancel=cancel)

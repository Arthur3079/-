"""Юнит-тесты для sonya.humanizer."""

from __future__ import annotations

import random

from sonya.humanizer import (
    AWARENESS_MAX_S,
    AWARENESS_MIN_S,
    TYPING_MAX_S,
    TYPING_MIN_S,
    calculate_timing,
)


def test_short_reply_uses_typing_min() -> None:
    timing = calculate_timing("hi", rng=random.Random(0))
    assert timing.typing_delay >= TYPING_MIN_S
    assert AWARENESS_MIN_S <= timing.awareness_delay <= AWARENESS_MAX_S


def test_long_reply_capped_at_typing_max() -> None:
    timing = calculate_timing("a" * 5000, rng=random.Random(0))
    assert timing.typing_delay == TYPING_MAX_S


def test_typing_delay_grows_with_length() -> None:
    rng = random.Random(0)
    short = calculate_timing("hello", rng=rng).typing_delay
    rng = random.Random(0)
    long = calculate_timing("hello there how is your day going today friend", rng=rng).typing_delay
    assert long >= short

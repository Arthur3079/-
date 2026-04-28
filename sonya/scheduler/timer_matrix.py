"""Timer matrix — per-stage proactive scheduling rules from the template library.

The master rail in `template_library.json` defines `timers` arrays on each
stage. Each timer says: "after N hours of silence in this stage, fire action X
using template_ref Y." This module:

1. Parses those JSON timers into typed `TimerRule` dataclasses.
2. Provides `get_timers(stage_id)` to look up applicable rules for a stage.
3. Provides `pick_timer_for_context(stage_id, archetype_id, attempt)` for the
   proactive engine to decide which followup to enqueue and when.

Ghost recovery stages (S9_*) have a multi-step sequence: D1 (24 h), D2 (48 h),
D3 (72 h). After D3 with no reply → fan moves to S_LOST.

The matrix is loaded once from the singleton `LIBRARY` at import time. Tests
can override via dependency injection (`library=...`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sonya.library.loader import LIBRARY, TemplateLibrary


@dataclass(frozen=True, slots=True)
class TimerRule:
    """One proactive-send rule for a stage."""

    stage_id: str
    after: timedelta
    action: str
    template_ref: str | None = None


# Ghost recovery is a 3-step escalating sequence. The JSON only defines one
# timer for S9_GHOST_NEW; we expand it into the canonical D1/D2/D3 sequence.
GHOST_RECOVERY_SEQUENCE: tuple[TimerRule, ...] = (
    TimerRule(
        stage_id="S9_GHOST_NEW",
        after=timedelta(hours=24),
        action="ghost_recovery_D1",
        template_ref="warmup.D1_check_in",
    ),
    TimerRule(
        stage_id="S9_GHOST_NEW",
        after=timedelta(hours=48),
        action="ghost_recovery_D2",
        template_ref="warmup.storybait",
    ),
    TimerRule(
        stage_id="S9_GHOST_NEW",
        after=timedelta(hours=72),
        action="ghost_recovery_D3",
        template_ref="warmup.memory_storybait",
    ),
)

# Welcome drip: new fans get a staged warm-up if they don't reply.
WELCOME_DRIP_SEQUENCE: tuple[TimerRule, ...] = (
    TimerRule(
        stage_id="S1_WELCOME",
        after=timedelta(hours=24),
        action="welcome_drip_D1",
        template_ref="warmup.D1_check_in",
    ),
    TimerRule(
        stage_id="S1_WELCOME",
        after=timedelta(hours=72),
        action="welcome_drip_D3",
        template_ref="warmup.storybait",
    ),
)

# Active-window hours (fan local time). We never send proactive messages
# outside this range.
PROACTIVE_SEND_WINDOW: tuple[int, int] = (9, 22)
"""(start_hour_inclusive, end_hour_exclusive) in fan's local timezone."""


def _build_matrix(library: TemplateLibrary) -> dict[str, tuple[TimerRule, ...]]:
    """Parse stage timers from the library into a lookup dict."""
    matrix: dict[str, list[TimerRule]] = {}

    for stage in library.master_stages:
        rules: list[TimerRule] = []
        for timer in stage.timers:
            rules.append(
                TimerRule(
                    stage_id=stage.id,
                    after=timedelta(hours=timer.after_h),
                    action=timer.action,
                    template_ref=timer.template_ref,
                )
            )
        if rules:
            matrix[stage.id] = rules

    # Override S9_GHOST_NEW with our expanded 3-step sequence.
    matrix["S9_GHOST_NEW"] = list(GHOST_RECOVERY_SEQUENCE)
    # Add S1_WELCOME drip (supplement the library's single 24h timer).
    matrix["S1_WELCOME"] = list(WELCOME_DRIP_SEQUENCE)

    return {k: tuple(v) for k, v in matrix.items()}


# Singleton loaded once at import.
TIMER_MATRIX: dict[str, tuple[TimerRule, ...]] = _build_matrix(LIBRARY)


def get_timers(stage_id: str, *, library: TemplateLibrary = LIBRARY) -> tuple[TimerRule, ...]:
    """Return timer rules for a given rail stage, or empty tuple if none."""
    if library is not LIBRARY:
        return _build_matrix(library).get(stage_id, ())
    return TIMER_MATRIX.get(stage_id, ())


def get_timer_for_attempt(
    stage_id: str,
    *,
    attempt: int = 0,
    library: TemplateLibrary = LIBRARY,
) -> TimerRule | None:
    """Return the timer rule for a specific attempt index (0-based).

    For ghost recovery: attempt 0 = D1, 1 = D2, 2 = D3. Returns None if
    the attempt exceeds available rules (sequence exhausted → move to S_LOST).
    """
    timers = get_timers(stage_id, library=library)
    if attempt < len(timers):
        return timers[attempt]
    return None


def is_in_send_window(fan_local_hour: int | None) -> bool:
    """True if the fan's local hour is within the proactive send window.

    Returns True when the hour is unknown (we err on the side of sending
    rather than silently dropping — the cadence gate is the last line).
    """
    if fan_local_hour is None:
        return True
    start, end = PROACTIVE_SEND_WINDOW
    return start <= fan_local_hour < end


__all__ = [
    "GHOST_RECOVERY_SEQUENCE",
    "PROACTIVE_SEND_WINDOW",
    "TIMER_MATRIX",
    "TimerRule",
    "WELCOME_DRIP_SEQUENCE",
    "get_timer_for_attempt",
    "get_timers",
    "is_in_send_window",
]

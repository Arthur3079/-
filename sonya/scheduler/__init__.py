"""Cadence engine: ghost recovery, aftercare, drip campaigns, proactive sends.

The scheduler reads pending rows from the `followups` table and dispatches
each at the right time. Sources of new followups:

- `ProactiveEngine.on_stage_transition`: auto-enqueues per the timer matrix.
- `enqueue_ghost_recovery`: classifier flagged a fan as GHOST → check-in copy.
- `enqueue_aftercare`: a `successful_payment` event landed → thank-you ping
  + CSAT-style follow-up.
- `enqueue_birthday`: facts contain `birthday: YYYY-MM-DD` → annual ping.

When a fan replies, `ProactiveEngine.on_fan_replied` (or `cancel_pending_for_fan`)
cancels all not-yet-executed followups so the bot doesn't ping an engaged fan.

Phase 3 additions:
- Timer matrix (per-stage timing rules from template_library.json).
- ProactiveEngine (stage-triggered enqueue + timezone gate + grain-aware messages).
- Multi-step sequences (ghost D1/D2/D3, welcome drip D1/D3).
"""

from sonya.scheduler.proactive import ProactiveEngine
from sonya.scheduler.repository import (
    cancel_pending_for_fan,
    due_followups,
    enqueue_followup,
    list_pending,
    mark_executed,
)
from sonya.scheduler.service import SchedulerService, build_followup_message
from sonya.scheduler.timer_matrix import (
    TIMER_MATRIX,
    TimerRule,
    get_timer_for_attempt,
    get_timers,
    is_in_send_window,
)

__all__ = [
    "ProactiveEngine",
    "SchedulerService",
    "TIMER_MATRIX",
    "TimerRule",
    "build_followup_message",
    "cancel_pending_for_fan",
    "due_followups",
    "enqueue_followup",
    "get_timer_for_attempt",
    "get_timers",
    "is_in_send_window",
    "list_pending",
    "mark_executed",
]

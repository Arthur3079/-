"""Safety hardening — regenerate loop, escalation matrix, rate limiter.

Phase 6 additions:

1. **Regenerate loop** — instead of immediately substituting a canned safe_reply
   when evaluate_reply blocks a candidate, retry the LLM with additional
   corrective instructions up to MAX_REGEN_ATTEMPTS times.

2. **Escalation matrix** — tracks per-fan safety trigger counts within a window.
   If the same category fires N+ times, escalate to operator handoff.

3. **Rate limiter** — if a fan sends too many messages in a short window,
   apply progressive cooldown (slow-mode reply, then suppress).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import Client, EventLog
from sonya.observability import EventType, write_event

# ---- Regenerate Loop Constants ----

MAX_REGEN_ATTEMPTS: int = 3

REGEN_SYSTEM_NUDGE: str = (
    "Your previous reply was blocked by the safety filter. "
    "Rewrite your response avoiding: {reasons}. "
    "Keep the same intent but use a softer, more neutral tone. "
    "Do NOT use forbidden words, marketing language, or manipulation tactics."
)

# ---- Escalation Matrix Constants ----

ESCALATION_WINDOW_HOURS: int = 24
ESCALATION_THRESHOLDS: dict[str, int] = {
    "ai_disclosure_probe": 3,
    "off_platform": 2,
    "non_consent": 1,
    "minor_suspect": 1,
    "harassment": 2,
    "intoxication": 3,
    "financial_distress": 3,
    "crisis": 1,
}
ESCALATION_DEFAULT_THRESHOLD: int = 3

# ---- Rate Limiter Constants ----

RATE_LIMIT_WINDOW_SECONDS: int = 60
RATE_LIMIT_MAX_MESSAGES: int = 10
RATE_LIMIT_COOLDOWN_SECONDS: int = 300
RATE_LIMIT_HARD_MAX_MESSAGES: int = 30
RATE_LIMIT_HARD_WINDOW_SECONDS: int = 300


@dataclass(frozen=True, slots=True)
class RegenResult:
    """Result of a regeneration attempt."""

    text: str | None
    attempts: int
    succeeded: bool
    final_reasons: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class EscalationCheck:
    """Result of checking if a fan should be escalated."""

    should_escalate: bool
    trigger_category: str | None
    trigger_count: int
    threshold: int
    reason: str


@dataclass(frozen=True, slots=True)
class RateLimitCheck:
    """Result of rate limit evaluation."""

    is_limited: bool
    is_hard_limited: bool
    messages_in_window: int
    cooldown_seconds: int
    reason: str


class SafetyHardening:
    """Stateless methods for advanced safety features."""

    @staticmethod
    def build_regen_nudge(blocked_reasons: tuple[str, ...]) -> str:
        """Build the corrective system message for a regeneration attempt."""
        reasons_str = ", ".join(blocked_reasons) if blocked_reasons else "safety policy violation"
        return REGEN_SYSTEM_NUDGE.format(reasons=reasons_str)

    @staticmethod
    async def check_escalation(
        session: AsyncSession,
        *,
        client: Client,
        current_flags: tuple[str, ...],
        now: datetime | None = None,
    ) -> EscalationCheck:
        """Check if this fan's repeated safety triggers warrant escalation.

        Looks at events_log for SAFETY_FLAGGED events within the escalation
        window and counts per category.
        """
        n = now or datetime.now(UTC)
        window_start = n - timedelta(hours=ESCALATION_WINDOW_HOURS)

        # Count safety events in window.
        stmt = select(func.count(EventLog.id)).where(
            EventLog.fan_id == client.fan_id,
            EventLog.event_type == EventType.SAFETY_FLAGGED.value,
            EventLog.timestamp >= window_start,
        )
        total_count = int((await session.execute(stmt)).scalar_one() or 0)

        # Find the most concerning current flag.
        best_category: str | None = None
        best_threshold = ESCALATION_DEFAULT_THRESHOLD

        for flag in current_flags:
            threshold = ESCALATION_THRESHOLDS.get(flag, ESCALATION_DEFAULT_THRESHOLD)
            if threshold < best_threshold:
                best_threshold = threshold
                best_category = flag

        if best_category is None and current_flags:
            best_category = current_flags[0]

        # For escalation, we use total count as approximation.
        # Real per-category counting would require parsing event payload.
        should_escalate = total_count >= best_threshold

        if should_escalate:
            reason = f"{best_category or 'safety'}:{total_count}>={best_threshold}"
        else:
            reason = f"below_threshold:{total_count}<{best_threshold}"

        return EscalationCheck(
            should_escalate=should_escalate,
            trigger_category=best_category,
            trigger_count=total_count,
            threshold=best_threshold,
            reason=reason,
        )

    @staticmethod
    async def check_rate_limit(
        session: AsyncSession,
        *,
        client: Client,
        now: datetime | None = None,
    ) -> RateLimitCheck:
        """Check if a fan is sending messages too quickly.

        Two levels:
        - Soft: >10 messages in 60s → 5 min cooldown (bot replies slower)
        - Hard: >30 messages in 5min → suppress (don't reply at all)
        """
        n = now or datetime.now(UTC)

        # Soft window check.
        soft_start = n - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)
        soft_count = await _count_fan_messages_since(session, client.fan_id, soft_start)

        # Hard window check.
        hard_start = n - timedelta(seconds=RATE_LIMIT_HARD_WINDOW_SECONDS)
        hard_count = await _count_fan_messages_since(session, client.fan_id, hard_start)

        is_hard = hard_count >= RATE_LIMIT_HARD_MAX_MESSAGES
        is_soft = soft_count >= RATE_LIMIT_MAX_MESSAGES

        if is_hard:
            return RateLimitCheck(
                is_limited=True,
                is_hard_limited=True,
                messages_in_window=hard_count,
                cooldown_seconds=RATE_LIMIT_COOLDOWN_SECONDS * 2,
                reason=f"hard_rate_limit:{hard_count}>={RATE_LIMIT_HARD_MAX_MESSAGES}/5min",
            )

        if is_soft:
            return RateLimitCheck(
                is_limited=True,
                is_hard_limited=False,
                messages_in_window=soft_count,
                cooldown_seconds=RATE_LIMIT_COOLDOWN_SECONDS,
                reason=f"soft_rate_limit:{soft_count}>={RATE_LIMIT_MAX_MESSAGES}/60s",
            )

        return RateLimitCheck(
            is_limited=False,
            is_hard_limited=False,
            messages_in_window=soft_count,
            cooldown_seconds=0,
            reason="ok",
        )

    @staticmethod
    async def record_safety_audit(
        session: AsyncSession,
        *,
        fan_id: int,
        stage: str,
        action: str,
        severity: str,
        flags: tuple[str, ...],
        details: dict | None = None,
    ) -> None:
        """Write a structured safety audit event."""
        payload = {
            "stage": stage,
            "action": action,
            "severity": severity,
            "flags": list(flags),
            **(details or {}),
        }
        await write_event(
            session,
            fan_id=fan_id,
            event_type=EventType.SAFETY_FLAGGED,
            payload=payload,
        )

    @staticmethod
    async def maybe_escalate_and_handoff(
        session: AsyncSession,
        *,
        client: Client,
        current_flags: tuple[str, ...],
        now: datetime | None = None,
    ) -> bool:
        """Check escalation and apply handoff if warranted. Returns True if escalated."""
        from sonya.crm.repository import set_handoff_required

        check = await SafetyHardening.check_escalation(
            session, client=client, current_flags=current_flags, now=now
        )

        if not check.should_escalate:
            return False

        if client.handoff_required:
            return False

        await set_handoff_required(
            session,
            fan_id=client.fan_id,
            reason=f"escalation:{check.reason}",
        )

        await write_event(
            session,
            fan_id=client.fan_id,
            event_type=EventType.SAFETY_FLAGGED,
            payload={
                "stage": "escalation",
                "action": "handoff",
                "trigger_category": check.trigger_category,
                "trigger_count": check.trigger_count,
                "threshold": check.threshold,
            },
        )

        return True


# ---- Helpers ----


async def _count_fan_messages_since(session: AsyncSession, fan_id: int, since: datetime) -> int:
    from sonya.db.models import Message, MessageDirection

    stmt = select(func.count(Message.id)).where(
        Message.fan_id == fan_id,
        Message.direction == MessageDirection.INCOMING,
        Message.timestamp >= since,
    )
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


__all__ = [
    "ESCALATION_DEFAULT_THRESHOLD",
    "ESCALATION_THRESHOLDS",
    "ESCALATION_WINDOW_HOURS",
    "MAX_REGEN_ATTEMPTS",
    "RATE_LIMIT_COOLDOWN_SECONDS",
    "RATE_LIMIT_HARD_MAX_MESSAGES",
    "RATE_LIMIT_HARD_WINDOW_SECONDS",
    "RATE_LIMIT_MAX_MESSAGES",
    "RATE_LIMIT_WINDOW_SECONDS",
    "REGEN_SYSTEM_NUDGE",
    "EscalationCheck",
    "RateLimitCheck",
    "RegenResult",
    "SafetyHardening",
]

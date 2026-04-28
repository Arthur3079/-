"""SafetyEngine — applies a `SafetyVerdict` to the CRM and event log.

`evaluate_incoming` / `evaluate_reply` are pure functions: they look at a
single message and return a `SafetyVerdict`. They do not know about the DB.

`SafetyEngine.precheck` wraps `evaluate_incoming` and:
- merges the incoming verdict with the fan's persisted history (e.g. "fan
  was already flagged as vulnerable two turns ago"),
- writes the resulting flags / risk_level / suppression / handoff back to
  the `clients` row via the CRM repository,
- records a `safety_flagged` row in `events_log` whenever any field
  changes.

This is the single entry point the dialogue/handler layer uses. The engine
is intentionally thin: all the rule logic stays in `rules.py` so it can be
unit-tested without a database.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.crm.flags import has_flag
from sonya.crm.repository import (
    is_suppressed,
    set_handoff_required,
    set_suppression_for,
    update_risk_level,
    update_safety_flags,
)
from sonya.db.models import Client
from sonya.journey import RiskLevel
from sonya.observability import EventType, write_event
from sonya.safety.rules import (
    SafetyAction,
    SafetySeverity,
    SafetyVerdict,
    evaluate_incoming,
    evaluate_reply,
)
from sonya.scheduler.repository import cancel_pending_for_fan

_RISK_ORDER = {
    RiskLevel.NONE: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


@dataclass(frozen=True)
class SafetyOutcome:
    """Result of `SafetyEngine.precheck` after persistence side effects."""

    verdict: SafetyVerdict
    suppression_applied: bool
    handoff_applied: bool
    flags_added: tuple[str, ...]
    persisted_risk_level: RiskLevel
    already_suppressed: bool


class SafetyEngine:
    """Stateless façade. Holds no fields; methods take `session` + `client`."""

    @staticmethod
    async def precheck(
        session: AsyncSession,
        *,
        client: Client,
        text: str,
    ) -> SafetyOutcome:
        """Run pre-LLM safety check + persist its decisions.

        - Reads `client.flags` to decide if the fan was previously flagged
          (so e.g. a second non-consent ask escalates).
        - Calls `evaluate_incoming(text, fan_already_flagged=...)`.
        - If the verdict raises risk_level above current, persists the new
          level via `update_risk_level`.
        - If the verdict carries new flags not yet on the client, persists
          them via `update_safety_flags`.
        - If `verdict.suppression_hours` is set, calls
          `set_suppression_for`.
        - If `verdict.handoff_required`, calls `set_handoff_required`.
        - Writes `safety_flagged` to events_log with the verdict payload.
        """
        already = _fan_already_flagged(client)
        verdict = evaluate_incoming(text, fan_already_flagged=already)

        flags_added: tuple[str, ...] = ()
        new_flags = tuple(f for f in verdict.effective_flags if not has_flag(client.flags, f))
        if new_flags:
            await update_safety_flags(session, fan_id=client.fan_id, add=list(new_flags))
            flags_added = new_flags

        persisted_risk = RiskLevel(client.risk_level or RiskLevel.NONE.value)
        new_risk = verdict.effective_risk_level
        if _RISK_ORDER[new_risk] > _RISK_ORDER[persisted_risk]:
            await update_risk_level(
                session,
                fan_id=client.fan_id,
                risk_level=new_risk,
                reason="safety_pre",
            )
            persisted_risk = new_risk

        suppression_applied = False
        followups_cancelled = 0
        if verdict.suppression_hours is not None and verdict.suppression_hours > 0:
            await set_suppression_for(
                session,
                fan_id=client.fan_id,
                hours=verdict.suppression_hours,
                reason=",".join(verdict.effective_flags) or "safety",
            )
            suppression_applied = True
            # Layer 5: any new suppression cancels every pending followup
            # for this fan. We don't want a thank-you ping firing 24h after
            # a fan asked us to stop.
            followups_cancelled = await cancel_pending_for_fan(
                session,
                fan_id=client.fan_id,
                reason=f"suppression:{','.join(verdict.effective_flags) or 'safety'}",
            )

        already_suppressed = await is_suppressed(session, fan_id=client.fan_id)

        handoff_applied = False
        if verdict.handoff_required and not client.handoff_required:
            await set_handoff_required(
                session,
                fan_id=client.fan_id,
                reason=",".join(verdict.effective_flags) or "safety",
            )
            handoff_applied = True
            # Layer 5: handoff also cancels pending followups so a human
            # operator decides what (if anything) goes out next.
            if followups_cancelled == 0:
                followups_cancelled = await cancel_pending_for_fan(
                    session,
                    fan_id=client.fan_id,
                    reason=f"handoff:{','.join(verdict.effective_flags) or 'safety'}",
                )

        if verdict.action is not SafetyAction.ALLOW or new_flags:
            await write_event(
                session,
                fan_id=client.fan_id,
                event_type=EventType.SAFETY_FLAGGED,
                payload={
                    "stage": "pre",
                    "action": verdict.action.value,
                    "severity": verdict.severity.value,
                    "risk_level": verdict.effective_risk_level.value,
                    "flags": list(verdict.effective_flags),
                    "sales_allowed": verdict.effective_sales_allowed,
                    "proactive_allowed": verdict.effective_proactive_allowed,
                    "suppression_hours": verdict.suppression_hours,
                    "safe_reply_type": verdict.safe_reply_type,
                    "handoff_required": verdict.handoff_required,
                    "fan_already_flagged": already,
                    "followups_cancelled": followups_cancelled,
                },
            )

        if verdict.action is not SafetyAction.ALLOW:
            logger.warning(
                "Safety pre fan_id={} action={} sev={} flags={} suppress_h={} handoff={}",
                client.fan_id,
                verdict.action.value,
                verdict.severity.value,
                ",".join(verdict.effective_flags) or "-",
                verdict.suppression_hours,
                verdict.handoff_required,
            )

        return SafetyOutcome(
            verdict=verdict,
            suppression_applied=suppression_applied,
            handoff_applied=handoff_applied,
            flags_added=flags_added,
            persisted_risk_level=persisted_risk,
            already_suppressed=already_suppressed,
        )

    @staticmethod
    async def postcheck(
        session: AsyncSession,
        *,
        client: Client,
        text: str,
        incoming_text: str | None = None,
    ) -> SafetyVerdict:
        """Run post-LLM safety check on a candidate outgoing reply.

        Accepts the original `incoming_text` so the pre-send 9-checklist can
        evaluate tempo / length-ratio (MR1). `fan_name` and `fan_language`
        are read off the `client` row.

        We log a `safety_flagged` event when the post-check blocks the
        reply, but we do **not** persist suppression/handoff here — those
        are pre-check decisions. Persisting state from the model's mistake
        would let a flaky LLM punish a clean fan.
        """
        verdict = evaluate_reply(
            text,
            incoming_text=incoming_text,
            fan_name=client.known_name or client.first_name,
            fan_language=client.language,
        )
        if verdict.action is not SafetyAction.ALLOW:
            await write_event(
                session,
                fan_id=client.fan_id,
                event_type=EventType.SAFETY_FLAGGED,
                payload={
                    "stage": "post",
                    "action": verdict.action.value,
                    "severity": verdict.severity.value,
                    "flags": list(verdict.effective_flags),
                    "candidate_len": len(text),
                },
            )
            logger.warning(
                "Safety post fan_id={} action={} flags={}",
                client.fan_id,
                verdict.action.value,
                ",".join(verdict.effective_flags) or "-",
            )
        return verdict


def _fan_already_flagged(client: Client) -> bool:
    """True if the client carries any persisted high-risk safety flag.

    Used to escalate borderline categories (e.g. a second non-consent ask
    becomes handoff). We treat anything other than `intoxication`,
    `financial_distress`, `ai_disclosure_probe` as "already flagged".
    """
    raw = client.flags or ""
    if not raw:
        return False
    benign = {"intoxication", "financial_distress", "ai_disclosure_probe"}
    return any(f.strip() and f.strip() not in benign for f in raw.split(","))


__all__ = ["SafetyEngine", "SafetyOutcome", "SafetySeverity", "SafetyVerdict"]

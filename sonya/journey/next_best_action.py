"""NextBestAction — pick the action Sonya should take this turn.

Inputs are everything the dialogue layer already has after running safety
+ journey + cadence:

- `stage: Stage` — current journey stage
- `safety_outcome: SafetyOutcome | SafetyVerdict` — hard limits
- `cadence_offer: CadenceVerdict` — whether sales offer is OK
- `cadence_reply: CadenceVerdict` — whether we may reply at all
- `intent: Intent` — what the fan asked for

Output is one `NextAction`. The dialogue layer maps that to concrete
DialogueResult fields (e.g. APPEND_OFFER → call sales recommendation;
DROP → return reply_text=None; HANDOFF → set DialogueResult.handoff_required).

Action precedence (first match wins):

1. `DROP_SILENTLY` — safety said drop (e.g. stop_request).
2. `HANDOFF` — handoff required by safety, or stage = HANDOFF.
3. `SAFE_REPLY` — safety blocked but provided a canned reply.
4. `NO_REPLY` — cadence forbids replying (suppressed, paused).
5. `REPLY_WITH_OFFER` — buying-intent + cadence allows offer.
6. `REPLY_NORMAL` — default.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from sonya.cadence import CadenceVerdict
from sonya.journey.stages import Stage
from sonya.safety import SafetyAction, SafetyVerdict

if TYPE_CHECKING:  # pragma: no cover
    from sonya.dialogue.intent import Intent


class NextAction(str, Enum):
    DROP_SILENTLY = "drop_silently"
    HANDOFF = "handoff"
    SAFE_REPLY = "safe_reply"
    NO_REPLY = "no_reply"
    REPLY_WITH_OFFER = "reply_with_offer"
    REPLY_NORMAL = "reply_normal"


_BUYING_INTENTS: frozenset[str] = frozenset(
    {"content_request", "price_question", "payment_question"}
)


@dataclass(frozen=True)
class NextBestActionResult:
    action: NextAction
    reason: str
    safe_reply: str | None = None


def select_next_best_action(
    *,
    stage: Stage,
    safety_verdict: SafetyVerdict,
    cadence_offer: CadenceVerdict,
    cadence_reply: CadenceVerdict,
    intent: Intent | None,
) -> NextBestActionResult:
    """Compute one `NextAction` from the layered verdicts."""
    if safety_verdict.action is SafetyAction.DROP_SILENTLY:
        return NextBestActionResult(
            action=NextAction.DROP_SILENTLY,
            reason="safety_drop",
        )

    if safety_verdict.handoff_required or stage is Stage.HANDOFF:
        return NextBestActionResult(
            action=NextAction.HANDOFF,
            reason="handoff_required",
            safe_reply=safety_verdict.safe_reply,
        )

    if safety_verdict.action is SafetyAction.HANDOFF_TO_HUMAN:
        return NextBestActionResult(
            action=NextAction.HANDOFF,
            reason="safety_handoff",
            safe_reply=safety_verdict.safe_reply,
        )

    if safety_verdict.action is SafetyAction.REPLACE_WITH_SAFE_REPLY:
        return NextBestActionResult(
            action=NextAction.SAFE_REPLY,
            reason="safety_safe_reply",
            safe_reply=safety_verdict.safe_reply,
        )

    if not cadence_reply.allowed:
        return NextBestActionResult(
            action=NextAction.NO_REPLY,
            reason=f"cadence:{cadence_reply.reason}",
        )

    intent_value = intent.value if intent is not None else ""
    if intent_value in _BUYING_INTENTS and cadence_offer.allowed:
        return NextBestActionResult(
            action=NextAction.REPLY_WITH_OFFER,
            reason="buying_intent_offer_allowed",
        )

    return NextBestActionResult(action=NextAction.REPLY_NORMAL, reason="default")


__all__ = ["NextAction", "NextBestActionResult", "select_next_best_action"]

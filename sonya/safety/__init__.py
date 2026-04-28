"""Deterministic safety layer.

The system prompt asks the LLM to behave; this layer makes sure that even if
the LLM goes off the rails (or the fan probes for unsafe content), we either
refuse / pivot / handoff *before* the user ever sees a problematic reply.

Hard rules live in code, not in markdown:
    - minors / underage roleplay
    - non-consent / coercion
    - off-platform payment / contact attempts
    - crisis (self-harm, suicide ideation) → handoff, never sales
    - financial pressure on vulnerable users
    - AI-disclosure deflection (we never affirm "I'm AI" in DMs, but we also
      never lie about it under direct pressure — we deflect / handoff)

See `sonya/safety/rules.py` for the implementation, and
`knowledge/ai_training/06_AI_stop_list.md` /
`knowledge/ai_training/15_crisis_safety_playbook.md` for the source of truth
that this module encodes.
"""

from sonya.safety.engine import SafetyEngine, SafetyOutcome
from sonya.safety.rules import (
    SafetyAction,
    SafetySeverity,
    SafetyVerdict,
    evaluate_incoming,
    evaluate_reply,
)

__all__ = [
    "SafetyAction",
    "SafetyEngine",
    "SafetyOutcome",
    "SafetySeverity",
    "SafetyVerdict",
    "evaluate_incoming",
    "evaluate_reply",
]

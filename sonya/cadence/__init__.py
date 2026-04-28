"""CadenceEngine — gates outgoing messages on cooldowns + safety state.

Three gates:
- `should_proactively_send(client, *, proactive_allowed)` — used by
  followup/scheduler logic. Refuses if suppression active, handoff
  required, or `consecutive_outbound_without_reply` >= MAX_OUTBOUND_BURST.
- `should_offer_sales(client, stage, *, sales_allowed, recent_inbound_count)`
  — used by the dialogue layer's recommend branch. Enforces the
  audit-mandated minimums: no PPV in the first N messages, 24h cooldown
  between offers, no offers in unsafe stages.
- `should_reply(client)` — used by the dialogue layer to short-circuit if
  the fan is suppressed/handoff (we still update CRM, but don't talk).

This module is pure (no DB writes). Callers hold the verdict + client
already in hand from upstream layers.
"""

from sonya.cadence.engine import (
    MAX_OUTBOUND_BURST,
    MIN_INBOUND_BEFORE_OFFER,
    OFFER_COOLDOWN,
    CadenceEngine,
    CadenceVerdict,
)

__all__ = [
    "CadenceEngine",
    "CadenceVerdict",
    "MAX_OUTBOUND_BURST",
    "MIN_INBOUND_BEFORE_OFFER",
    "OFFER_COOLDOWN",
]

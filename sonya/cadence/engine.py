"""CadenceEngine — pure-function gating for sales offers + proactive sends.

Constants:
- `MIN_INBOUND_BEFORE_OFFER` (default 5): no PPV in the first N inbound
  turns; per the audit's recommended sales gating.
- `OFFER_COOLDOWN` (default 24h): minimum gap between two offers to the
  same fan.
- `MAX_OUTBOUND_BURST` (default 3): we never send a 4th outbound in a row
  without an inbound between them.

`CadenceVerdict` carries:
- `allowed: bool` — whether the action is permitted.
- `reason: str` — human/log reason if blocked. Empty when allowed.
- `metadata`: dict for the events_log payload (e.g. seconds-until-cooldown).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sonya.crm.flags import has_flag
from sonya.db.models import Client
from sonya.journey.stages import Stage

MIN_INBOUND_BEFORE_OFFER = 5
OFFER_COOLDOWN = timedelta(hours=24)
MAX_OUTBOUND_BURST = 3

# Stages where Sonya should never push a sale, regardless of intent.
_STAGES_NO_SALES: frozenset[Stage] = frozenset({Stage.PAUSED_SAFETY, Stage.HANDOFF, Stage.GHOST})

# Flags that completely block sales offers (no upsell to vulnerable users).
_FLAGS_NO_SALES: frozenset[str] = frozenset(
    {
        "minors",
        "crisis",
        "stop_request",
        "harassment",
        "chargeback",
        "non_consent",
        "intoxication",
        "financial_distress",
        "vulnerable",
    }
)


def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


@dataclass(frozen=True)
class CadenceVerdict:
    allowed: bool
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class CadenceEngine:
    """Stateless. All methods are static and take everything they need."""

    @staticmethod
    def should_offer_sales(
        client: Client,
        *,
        stage: Stage,
        sales_allowed_by_safety: bool,
        recent_inbound_count: int,
        now: datetime | None = None,
    ) -> CadenceVerdict:
        """Gate sales-offer creation. Returns `allowed=False` with a `reason`
        when blocked so the caller can log it / emit an event.

        Order of checks (first failure wins):

        1. SafetyEngine already said no (`sales_allowed_by_safety=False`).
        2. Stage is in `_STAGES_NO_SALES`.
        3. Any sales-blocking flag on `client.flags`.
        4. Inbound history below `MIN_INBOUND_BEFORE_OFFER`.
        5. Last offer within `OFFER_COOLDOWN`.
        """
        n = now or datetime.now(UTC)

        if not sales_allowed_by_safety:
            return CadenceVerdict(allowed=False, reason="safety_blocks_sales")

        if stage in _STAGES_NO_SALES:
            return CadenceVerdict(
                allowed=False,
                reason="stage_blocks_sales",
                metadata={"stage": stage.value},
            )

        for flag in _FLAGS_NO_SALES:
            if has_flag(client.flags, flag):
                return CadenceVerdict(
                    allowed=False,
                    reason="flag_blocks_sales",
                    metadata={"flag": flag},
                )

        if recent_inbound_count < MIN_INBOUND_BEFORE_OFFER:
            return CadenceVerdict(
                allowed=False,
                reason="below_min_inbound",
                metadata={
                    "min_inbound": MIN_INBOUND_BEFORE_OFFER,
                    "have": recent_inbound_count,
                },
            )

        last_offer = _to_utc(client.last_offer_at)
        if last_offer is not None and (n - last_offer) < OFFER_COOLDOWN:
            seconds_left = (OFFER_COOLDOWN - (n - last_offer)).total_seconds()
            return CadenceVerdict(
                allowed=False,
                reason="offer_cooldown",
                metadata={"seconds_until_cooldown_clears": int(seconds_left)},
            )

        return CadenceVerdict(allowed=True)

    @staticmethod
    def should_proactively_send(
        client: Client,
        *,
        proactive_allowed_by_safety: bool = True,
        now: datetime | None = None,
    ) -> CadenceVerdict:
        """Gate proactive (follow-up / re-engagement) sends.

        Failure cases:
        - Safety blocked (`proactive_allowed_by_safety=False`).
        - Suppression active.
        - Handoff required.
        - Operator paused (`is_paused=True`).
        - Outbound-burst limit reached.
        """
        n = now or datetime.now(UTC)

        if not proactive_allowed_by_safety:
            return CadenceVerdict(allowed=False, reason="safety_blocks_proactive")

        sup = _to_utc(client.suppression_until)
        if sup is not None and sup > n:
            return CadenceVerdict(
                allowed=False,
                reason="suppressed",
                metadata={"until": sup.isoformat()},
            )

        if client.handoff_required:
            return CadenceVerdict(allowed=False, reason="handoff_required")

        if getattr(client, "is_paused", False):
            return CadenceVerdict(allowed=False, reason="operator_paused")

        if (client.consecutive_outbound_without_reply or 0) >= MAX_OUTBOUND_BURST:
            return CadenceVerdict(
                allowed=False,
                reason="outbound_burst_limit",
                metadata={
                    "limit": MAX_OUTBOUND_BURST,
                    "current": client.consecutive_outbound_without_reply or 0,
                },
            )

        return CadenceVerdict(allowed=True)

    @staticmethod
    def should_reply(client: Client, *, now: datetime | None = None) -> CadenceVerdict:
        """Decide whether to reply at all to an inbound message.

        We *do* reply through suppression in some cases (operator can lift),
        but if the fan asked us to stop (`stop_request`) the suppression
        check above means we drop. This helper is the conservative version
        used by the dialogue layer to avoid sending while in handoff.
        """
        n = now or datetime.now(UTC)

        if client.handoff_required:
            return CadenceVerdict(allowed=False, reason="handoff_required")

        sup = _to_utc(client.suppression_until)
        if sup is not None and sup > n:
            return CadenceVerdict(
                allowed=False,
                reason="suppressed",
                metadata={"until": sup.isoformat()},
            )

        if getattr(client, "is_paused", False):
            return CadenceVerdict(allowed=False, reason="operator_paused")

        return CadenceVerdict(allowed=True)

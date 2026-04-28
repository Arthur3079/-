"""WhaleEngine — VIP fan lifecycle management.

Whales (B1 archetype) are fans who meet elevated spending / engagement criteria.
They contribute ~80% of revenue and warrant:
- Faster ghost recovery (12h/24h/48h instead of 24h/48h/72h)
- Higher cadence ceiling (5 outbound vs 3 before reply required)
- Exclusive upsell tier logic
- Operator handoff triggers on burnout / custom requests
- Automatic fan_type promotion when detection signals fire

Detection signals (from template_library.json archetype B1):
- ≥4 purchases in 30 days
- ≥$300 spend in 30 days
- Single tip ≥$50
- Active 30+ days with consistent engagement

The engine is stateless; all inputs come from the session + client row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import Client, SaleOutcome, SalesAttempt
from sonya.observability import EventType, write_event

# ---- Thresholds ----

WHALE_SPEND_30D: float = 300.0
WHALE_PURCHASES_30D: int = 4
WHALE_SINGLE_TIP: float = 50.0
WHALE_MIN_ACTIVE_DAYS: int = 30
WHALE_LIFETIME_MIN: float = 100.0

# Retention thresholds: whale going cold.
WHALE_COOLING_DAYS: int = 3
WHALE_COLD_DAYS: int = 7

# VIP cadence overrides.
WHALE_MAX_OUTBOUND_BURST: int = 5
WHALE_GHOST_RECOVERY_HOURS: tuple[int, ...] = (12, 24, 48)

# Upsell: tier escalation intervals.
UPSELL_COOLDOWN_DAYS: int = 14
UPSELL_MAX_TIER: int = 5


@dataclass(frozen=True, slots=True)
class WhaleSignals:
    """Collected whale detection signals for a fan."""

    spend_30d: float
    purchases_30d: int
    max_single_purchase: float
    lifetime_spend: float
    days_active: int
    is_whale: bool
    confidence: str  # "low" | "mid" | "high"
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WhaleRetentionStatus:
    """Current retention state for a whale."""

    is_cooling: bool
    is_cold: bool
    days_silent: int
    should_handoff: bool
    handoff_reason: str | None


@dataclass(frozen=True, slots=True)
class UpsellRecommendation:
    """Whether and what to upsell to a whale."""

    eligible: bool
    current_tier: int
    next_tier: int | None
    reason: str


class WhaleEngine:
    """Stateless whale lifecycle operations."""

    @staticmethod
    async def detect_whale(
        session: AsyncSession,
        *,
        client: Client,
        now: datetime | None = None,
    ) -> WhaleSignals:
        """Evaluate whether a fan qualifies as a whale (B1 archetype).

        Checks multiple signals and returns a composite result with confidence.
        """
        n = now or datetime.now(UTC)
        reasons: list[str] = []

        # 30-day window for spend and purchase counts.
        window_start = n - timedelta(days=30)

        # Query sales data.
        purchases_30d = await _count_purchases_since(session, client.fan_id, window_start)
        spend_30d = await _sum_spend_since(session, client.fan_id, window_start)
        max_single = await _max_single_purchase(session, client.fan_id)
        lifetime_spend = client.total_spend_lifetime

        # Days active.
        first_seen = client.first_seen
        days_active = 0
        if first_seen is not None:
            fs = first_seen if first_seen.tzinfo else first_seen.replace(tzinfo=UTC)
            days_active = max(0, (n - fs).days)

        # Evaluate signals.
        signal_count = 0

        if spend_30d >= WHALE_SPEND_30D:
            reasons.append(f"spend_30d={spend_30d:.0f}≥{WHALE_SPEND_30D}")
            signal_count += 1

        if purchases_30d >= WHALE_PURCHASES_30D:
            reasons.append(f"purchases_30d={purchases_30d}≥{WHALE_PURCHASES_30D}")
            signal_count += 1

        if max_single >= WHALE_SINGLE_TIP:
            reasons.append(f"max_single={max_single:.0f}≥{WHALE_SINGLE_TIP}")
            signal_count += 1

        if days_active >= WHALE_MIN_ACTIVE_DAYS:
            reasons.append(f"days_active={days_active}≥{WHALE_MIN_ACTIVE_DAYS}")
            signal_count += 1

        if lifetime_spend >= WHALE_LIFETIME_MIN:
            reasons.append(f"lifetime≥{WHALE_LIFETIME_MIN}")
            signal_count += 1

        # Determine whale status and confidence.
        is_whale = signal_count >= 2 or lifetime_spend >= WHALE_SPEND_30D
        if signal_count >= 4:
            confidence = "high"
        elif signal_count >= 2:
            confidence = "mid"
        elif signal_count == 1 and lifetime_spend >= WHALE_LIFETIME_MIN:
            confidence = "low"
        else:
            confidence = "low"

        return WhaleSignals(
            spend_30d=spend_30d,
            purchases_30d=purchases_30d,
            max_single_purchase=max_single,
            lifetime_spend=lifetime_spend,
            days_active=days_active,
            is_whale=is_whale,
            confidence=confidence,
            reasons=tuple(reasons),
        )

    @staticmethod
    async def maybe_promote(
        session: AsyncSession,
        *,
        client: Client,
        signals: WhaleSignals | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Auto-promote fan to whale (B1) if detection signals qualify.

        Returns True if the fan_type was updated. Only promotes with mid/high
        confidence to avoid false positives.
        """
        if signals is None:
            signals = await WhaleEngine.detect_whale(session, client=client, now=now)

        if not signals.is_whale or signals.confidence == "low":
            return False

        # Already a whale — no-op.
        if client.fan_type and client.fan_type.upper() in ("B1", "WHALE"):
            return False

        from sonya.crm.repository import update_fan_type

        changed = await update_fan_type(
            session, fan_id=client.fan_id, fan_type="B1", confidence=signals.confidence
        )
        if changed:
            await write_event(
                session,
                fan_id=client.fan_id,
                event_type=EventType.FAN_TYPE_UPDATED,
                payload={
                    "promoted_to": "B1",
                    "confidence": signals.confidence,
                    "signals": signals.reasons,
                },
            )
        return changed

    @staticmethod
    def check_retention(
        client: Client,
        *,
        now: datetime | None = None,
    ) -> WhaleRetentionStatus:
        """Evaluate whale retention state — is this VIP going cold?

        Used by the proactive engine to decide urgency of re-engagement.
        """
        n = now or datetime.now(UTC)

        last_inbound = client.last_inbound_at
        if last_inbound is None:
            return WhaleRetentionStatus(
                is_cooling=False,
                is_cold=False,
                days_silent=0,
                should_handoff=False,
                handoff_reason=None,
            )

        if last_inbound.tzinfo is None:
            last_inbound = last_inbound.replace(tzinfo=UTC)

        days_silent = (n - last_inbound).days

        is_cooling = days_silent >= WHALE_COOLING_DAYS
        is_cold = days_silent >= WHALE_COLD_DAYS

        # Handoff trigger: whale has been cold AND we've already sent recovery
        # messages (consecutive_outbound ≥ 3 means we tried).
        outbound_count = client.consecutive_outbound_without_reply or 0
        should_handoff = is_cold and outbound_count >= 3
        handoff_reason = "whale_cold_unresponsive" if should_handoff else None

        return WhaleRetentionStatus(
            is_cooling=is_cooling,
            is_cold=is_cold,
            days_silent=days_silent,
            should_handoff=should_handoff,
            handoff_reason=handoff_reason,
        )

    @staticmethod
    def recommend_upsell(
        client: Client,
        *,
        now: datetime | None = None,
    ) -> UpsellRecommendation:
        """Decide whether to suggest a higher content tier to this whale.

        Logic:
        - Must be whale (B1) with at least one purchase.
        - Last offer must be > UPSELL_COOLDOWN_DAYS ago.
        - Current tier derived from total_spend_lifetime brackets.
        """
        n = now or datetime.now(UTC)

        if not client.fan_type or client.fan_type.upper() not in ("B1", "WHALE"):
            return UpsellRecommendation(
                eligible=False, current_tier=0, next_tier=None, reason="not_whale"
            )

        if client.last_purchase_at is None:
            return UpsellRecommendation(
                eligible=False, current_tier=0, next_tier=None, reason="no_purchases"
            )

        # Cooldown check.
        last_offer = client.last_offer_at
        if last_offer is not None:
            lo = last_offer if last_offer.tzinfo else last_offer.replace(tzinfo=UTC)
            if (n - lo).days < UPSELL_COOLDOWN_DAYS:
                return UpsellRecommendation(
                    eligible=False,
                    current_tier=_spend_to_tier(client.total_spend_lifetime),
                    next_tier=None,
                    reason="cooldown_active",
                )

        current_tier = _spend_to_tier(client.total_spend_lifetime)
        if current_tier >= UPSELL_MAX_TIER:
            return UpsellRecommendation(
                eligible=False,
                current_tier=current_tier,
                next_tier=None,
                reason="max_tier_reached",
            )

        return UpsellRecommendation(
            eligible=True,
            current_tier=current_tier,
            next_tier=current_tier + 1,
            reason="eligible",
        )

    @staticmethod
    def is_whale(client: Client) -> bool:
        """Quick check: is this fan currently labeled as a whale?"""
        return bool(client.fan_type and client.fan_type.upper() in ("B1", "WHALE"))


# ---- Helpers ----


def _spend_to_tier(lifetime_spend: float) -> int:
    """Map lifetime spend to a content tier (1–5)."""
    if lifetime_spend >= 1000:
        return 5
    if lifetime_spend >= 500:
        return 4
    if lifetime_spend >= 300:
        return 3
    if lifetime_spend >= 150:
        return 2
    return 1


async def _count_purchases_since(session: AsyncSession, fan_id: int, since: datetime) -> int:
    stmt = select(func.count(SalesAttempt.id)).where(
        SalesAttempt.fan_id == fan_id,
        SalesAttempt.outcome == SaleOutcome.PURCHASED,
        SalesAttempt.attempted_at >= since,
    )
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


async def _sum_spend_since(session: AsyncSession, fan_id: int, since: datetime) -> float:
    stmt = select(func.coalesce(func.sum(SalesAttempt.amount_usd_equivalent), 0.0)).where(
        SalesAttempt.fan_id == fan_id,
        SalesAttempt.outcome == SaleOutcome.PURCHASED,
        SalesAttempt.attempted_at >= since,
    )
    result = await session.execute(stmt)
    return float(result.scalar_one() or 0.0)


async def _max_single_purchase(session: AsyncSession, fan_id: int) -> float:
    stmt = select(func.coalesce(func.max(SalesAttempt.amount_usd_equivalent), 0.0)).where(
        SalesAttempt.fan_id == fan_id,
        SalesAttempt.outcome == SaleOutcome.PURCHASED,
    )
    result = await session.execute(stmt)
    return float(result.scalar_one() or 0.0)


__all__ = [
    "UPSELL_COOLDOWN_DAYS",
    "UPSELL_MAX_TIER",
    "WHALE_COLD_DAYS",
    "WHALE_COOLING_DAYS",
    "WHALE_GHOST_RECOVERY_HOURS",
    "WHALE_LIFETIME_MIN",
    "WHALE_MAX_OUTBOUND_BURST",
    "WHALE_MIN_ACTIVE_DAYS",
    "WHALE_PURCHASES_30D",
    "WHALE_SINGLE_TIP",
    "WHALE_SPEND_30D",
    "UpsellRecommendation",
    "WhaleEngine",
    "WhaleRetentionStatus",
    "WhaleSignals",
]

"""KPI metrics engine — compute business metrics from DB.

Provides:
- GlobalMetrics: org-wide KPIs (response rate, conversion, revenue, churn)
- FanStats: per-fan breakdown (messages, spend, stage, safety flags)
- SafetyStats: safety system performance (block counts, types, trends)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import (
    Client,
    EventLog,
    Message,
    MessageDirection,
    SaleOutcome,
    SalesAttempt,
)


@dataclass(frozen=True, slots=True)
class GlobalMetrics:
    """Org-wide KPIs for a given time window."""

    total_fans: int
    active_fans: int
    new_fans: int
    total_messages_in: int
    total_messages_out: int
    response_rate: float  # outbound / inbound ratio
    total_revenue: float
    total_purchases: int
    conversion_rate: float  # fans with ≥1 purchase / active fans
    avg_revenue_per_fan: float
    churned_fans: int
    churn_rate: float
    safety_blocks: int
    handoff_count: int
    whale_count: int


@dataclass(frozen=True, slots=True)
class FanStats:
    """Per-fan statistics."""

    fan_id: int
    display_name: str | None
    fan_type: str | None
    current_stage: str | None
    total_messages_in: int
    total_messages_out: int
    total_spend: float
    purchase_count: int
    days_active: int
    last_active: datetime | None
    flags: str | None
    risk_level: str | None
    is_suppressed: bool
    is_handoff: bool


@dataclass(frozen=True, slots=True)
class SafetyStats:
    """Safety system performance metrics."""

    total_blocks: int
    blocks_by_type: dict[str, int]
    handoffs_triggered: int
    escalations: int
    regen_successes: int
    regen_failures: int


class KPIEngine:
    """Stateless metrics computation from DB."""

    @staticmethod
    async def global_metrics(
        session: AsyncSession,
        *,
        window_days: int = 30,
        now: datetime | None = None,
    ) -> GlobalMetrics:
        """Compute org-wide KPIs for the given time window."""
        n = now or datetime.now(UTC)
        window_start = n - timedelta(days=window_days)

        # Total fans.
        total_fans = int(
            (await session.execute(select(func.count(Client.fan_id)))).scalar_one() or 0
        )

        # Active fans (sent a message in window).
        active_fans = int(
            (
                await session.execute(
                    select(func.count(func.distinct(Message.fan_id))).where(
                        Message.direction == MessageDirection.INCOMING,
                        Message.timestamp >= window_start,
                    )
                )
            ).scalar_one()
            or 0
        )

        # New fans (first_seen in window).
        new_fans = int(
            (
                await session.execute(
                    select(func.count(Client.fan_id)).where(Client.first_seen >= window_start)
                )
            ).scalar_one()
            or 0
        )

        # Messages counts.
        total_messages_in = int(
            (
                await session.execute(
                    select(func.count(Message.id)).where(
                        Message.direction == MessageDirection.INCOMING,
                        Message.timestamp >= window_start,
                    )
                )
            ).scalar_one()
            or 0
        )
        total_messages_out = int(
            (
                await session.execute(
                    select(func.count(Message.id)).where(
                        Message.direction == MessageDirection.OUTGOING,
                        Message.timestamp >= window_start,
                    )
                )
            ).scalar_one()
            or 0
        )

        response_rate = total_messages_out / total_messages_in if total_messages_in > 0 else 0.0

        # Revenue.
        total_revenue = float(
            (
                await session.execute(
                    select(func.coalesce(func.sum(SalesAttempt.amount_usd_equivalent), 0.0)).where(
                        SalesAttempt.outcome == SaleOutcome.PURCHASED,
                        SalesAttempt.attempted_at >= window_start,
                    )
                )
            ).scalar_one()
            or 0.0
        )

        total_purchases = int(
            (
                await session.execute(
                    select(func.count(SalesAttempt.id)).where(
                        SalesAttempt.outcome == SaleOutcome.PURCHASED,
                        SalesAttempt.attempted_at >= window_start,
                    )
                )
            ).scalar_one()
            or 0
        )

        # Conversion: fans who purchased / active fans.
        fans_who_purchased = int(
            (
                await session.execute(
                    select(func.count(func.distinct(SalesAttempt.fan_id))).where(
                        SalesAttempt.outcome == SaleOutcome.PURCHASED,
                        SalesAttempt.attempted_at >= window_start,
                    )
                )
            ).scalar_one()
            or 0
        )
        conversion_rate = fans_who_purchased / active_fans if active_fans > 0 else 0.0
        avg_revenue = total_revenue / active_fans if active_fans > 0 else 0.0

        # Churn: fans active previously but not in current window.
        prev_start = window_start - timedelta(days=window_days)
        prev_active = int(
            (
                await session.execute(
                    select(func.count(func.distinct(Message.fan_id))).where(
                        Message.direction == MessageDirection.INCOMING,
                        Message.timestamp >= prev_start,
                        Message.timestamp < window_start,
                    )
                )
            ).scalar_one()
            or 0
        )
        if prev_active > 0:
            still_active = int(
                (
                    await session.execute(
                        select(func.count(func.distinct(Message.fan_id))).where(
                            Message.direction == MessageDirection.INCOMING,
                            Message.timestamp >= window_start,
                            Message.fan_id.in_(
                                select(func.distinct(Message.fan_id)).where(
                                    Message.direction == MessageDirection.INCOMING,
                                    Message.timestamp >= prev_start,
                                    Message.timestamp < window_start,
                                )
                            ),
                        )
                    )
                ).scalar_one()
                or 0
            )
            churned = prev_active - still_active
            churn_rate = churned / prev_active
        else:
            churned = 0
            churn_rate = 0.0

        # Safety blocks.
        safety_blocks = int(
            (
                await session.execute(
                    select(func.count(EventLog.id)).where(
                        EventLog.event_type == "safety_flagged",
                        EventLog.timestamp >= window_start,
                    )
                )
            ).scalar_one()
            or 0
        )

        # Handoffs.
        handoff_count = int(
            (
                await session.execute(
                    select(func.count(Client.fan_id)).where(Client.handoff_required.is_(True))
                )
            ).scalar_one()
            or 0
        )

        # Whales.
        whale_count = int(
            (
                await session.execute(
                    select(func.count(Client.fan_id)).where(
                        func.upper(Client.fan_type) == "B1",
                    )
                )
            ).scalar_one()
            or 0
        )

        return GlobalMetrics(
            total_fans=total_fans,
            active_fans=active_fans,
            new_fans=new_fans,
            total_messages_in=total_messages_in,
            total_messages_out=total_messages_out,
            response_rate=round(response_rate, 3),
            total_revenue=round(total_revenue, 2),
            total_purchases=total_purchases,
            conversion_rate=round(conversion_rate, 3),
            avg_revenue_per_fan=round(avg_revenue, 2),
            churned_fans=churned,
            churn_rate=round(churn_rate, 3),
            safety_blocks=safety_blocks,
            handoff_count=handoff_count,
            whale_count=whale_count,
        )

    @staticmethod
    async def fan_stats(
        session: AsyncSession,
        *,
        fan_id: int,
        now: datetime | None = None,
    ) -> FanStats | None:
        """Compute stats for a single fan."""
        n = now or datetime.now(UTC)
        client = (
            await session.execute(select(Client).where(Client.fan_id == fan_id))
        ).scalar_one_or_none()
        if client is None:
            return None

        msgs_in = int(
            (
                await session.execute(
                    select(func.count(Message.id)).where(
                        Message.fan_id == fan_id,
                        Message.direction == MessageDirection.INCOMING,
                    )
                )
            ).scalar_one()
            or 0
        )

        msgs_out = int(
            (
                await session.execute(
                    select(func.count(Message.id)).where(
                        Message.fan_id == fan_id,
                        Message.direction == MessageDirection.OUTGOING,
                    )
                )
            ).scalar_one()
            or 0
        )

        purchase_count = int(
            (
                await session.execute(
                    select(func.count(SalesAttempt.id)).where(
                        SalesAttempt.fan_id == fan_id,
                        SalesAttempt.outcome == SaleOutcome.PURCHASED,
                    )
                )
            ).scalar_one()
            or 0
        )

        days_active = 0
        if client.first_seen:
            fs = client.first_seen
            if fs.tzinfo is None:
                fs = fs.replace(tzinfo=UTC)
            days_active = max(0, (n - fs).days)

        is_suppressed = False
        if client.suppression_until:
            su = client.suppression_until
            if su.tzinfo is None:
                su = su.replace(tzinfo=UTC)
            is_suppressed = su > n

        return FanStats(
            fan_id=client.fan_id,
            display_name=client.display_name,
            fan_type=client.fan_type,
            current_stage=client.current_stage,
            total_messages_in=msgs_in,
            total_messages_out=msgs_out,
            total_spend=client.total_spend_lifetime,
            purchase_count=purchase_count,
            days_active=days_active,
            last_active=client.last_active,
            flags=client.flags,
            risk_level=client.risk_level,
            is_suppressed=is_suppressed,
            is_handoff=client.handoff_required,
        )

    @staticmethod
    async def safety_stats(
        session: AsyncSession,
        *,
        window_days: int = 30,
        now: datetime | None = None,
    ) -> SafetyStats:
        """Compute safety system metrics."""
        n = now or datetime.now(UTC)
        window_start = n - timedelta(days=window_days)

        total_blocks = int(
            (
                await session.execute(
                    select(func.count(EventLog.id)).where(
                        EventLog.event_type == "safety_flagged",
                        EventLog.timestamp >= window_start,
                    )
                )
            ).scalar_one()
            or 0
        )

        handoffs = int(
            (
                await session.execute(
                    select(func.count(EventLog.id)).where(
                        EventLog.event_type == "handoff_required",
                        EventLog.timestamp >= window_start,
                    )
                )
            ).scalar_one()
            or 0
        )

        # Approximate regen stats by counting events with "regen_success" or
        # "regen_exhausted" in payload. Since payload is JSON text, use LIKE.
        regen_successes = int(
            (
                await session.execute(
                    select(func.count(EventLog.id)).where(
                        EventLog.event_type == "safety_flagged",
                        EventLog.timestamp >= window_start,
                        EventLog.payload.like('%"regen_success"%'),
                    )
                )
            ).scalar_one()
            or 0
        )

        regen_failures = int(
            (
                await session.execute(
                    select(func.count(EventLog.id)).where(
                        EventLog.event_type == "safety_flagged",
                        EventLog.timestamp >= window_start,
                        EventLog.payload.like('%"regen_exhausted"%'),
                    )
                )
            ).scalar_one()
            or 0
        )

        return SafetyStats(
            total_blocks=total_blocks,
            blocks_by_type={},  # Would require JSON parsing; keep simple for now
            handoffs_triggered=handoffs,
            escalations=0,  # Placeholder for detailed escalation tracking
            regen_successes=regen_successes,
            regen_failures=regen_failures,
        )

    @staticmethod
    async def top_fans(
        session: AsyncSession,
        *,
        limit: int = 10,
        order_by: str = "spend",
    ) -> list[FanStats]:
        """Return top fans ranked by spend or activity."""
        if order_by == "spend":
            stmt = select(Client).order_by(Client.total_spend_lifetime.desc()).limit(limit)
        else:
            stmt = select(Client).order_by(Client.last_active.desc().nulls_last()).limit(limit)

        rows = (await session.execute(stmt)).scalars().all()
        results = []
        for client in rows:
            stats = await KPIEngine.fan_stats(session, fan_id=client.fan_id)
            if stats:
                results.append(stats)
        return results


def render_global_metrics(m: GlobalMetrics) -> str:
    """Render global metrics as a human-readable admin report."""
    lines = [
        "📊 KPI Dashboard",
        f"{'─' * 30}",
        f"👥 Fans: {m.total_fans} total, {m.active_fans} active, {m.new_fans} new",
        f"💬 Messages: {m.total_messages_in} in / {m.total_messages_out} out (rate: {m.response_rate:.1%})",
        f"💰 Revenue: ${m.total_revenue:.2f} ({m.total_purchases} purchases)",
        f"📈 Conversion: {m.conversion_rate:.1%}, ARPU: ${m.avg_revenue_per_fan:.2f}",
        f"📉 Churn: {m.churned_fans} fans ({m.churn_rate:.1%})",
        f"🐋 Whales: {m.whale_count}",
        f"🛡️ Safety blocks: {m.safety_blocks}, Handoffs: {m.handoff_count}",
    ]
    return "\n".join(lines)


def render_fan_stats(s: FanStats) -> str:
    """Render per-fan stats."""
    lines = [
        f"👤 Fan #{s.fan_id}: {s.display_name or 'unknown'}",
        f"   Type: {s.fan_type or '-'} | Stage: {s.current_stage or '-'}",
        f"   Messages: {s.total_messages_in} in / {s.total_messages_out} out",
        f"   Spend: ${s.total_spend:.2f} ({s.purchase_count} purchases)",
        f"   Active: {s.days_active}d | Last: {s.last_active.strftime('%Y-%m-%d') if s.last_active else '-'}",
        f"   Risk: {s.risk_level or 'none'} | Flags: {s.flags or '-'}",
    ]
    if s.is_suppressed:
        lines.append("   ⚠️ SUPPRESSED")
    if s.is_handoff:
        lines.append("   🔴 HANDOFF REQUIRED")
    return "\n".join(lines)


__all__ = [
    "FanStats",
    "GlobalMetrics",
    "KPIEngine",
    "SafetyStats",
    "render_fan_stats",
    "render_global_metrics",
]

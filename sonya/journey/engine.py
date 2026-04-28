"""JourneyEngine — classify a fan's current `Stage` from CRM state.

Stage is a derived quantity. Inputs:
- `client.suppression_until`, `client.handoff_required` — short-circuit to
  PAUSED_SAFETY / HANDOFF if either is true.
- `client.last_purchase_at` — drives AFTERCARE → REPEAT_READY.
- `client.last_offer_at` — drives OFFER_PENDING (fan was just sent a CTA
  but hasn't paid yet).
- `client.last_inbound_at` — drives GHOST.
- inbound message count (recent history) — drives WELCOME → WARMUP →
  QUALIFY.

The engine is pure: no DB writes, no event emission. The caller is
responsible for persisting any stage change via `update_stage(...)` if they
want it on the row. We expose two helpers:

- `classify_stage(client, *, recent_inbound_count, now)` → `Stage`
- `JourneyEngine.classify_and_persist(session, client, recent_inbound_count)`
  → `(stage, changed)` — convenience wrapper.

Thresholds live as module-level constants so they're easy to tune.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from sonya.crm.repository import update_stage
from sonya.db.models import Client
from sonya.journey.stages import Stage

WARMUP_MIN_INBOUND = 1
QUALIFY_MIN_INBOUND = 4
OFFER_PENDING_WINDOW = timedelta(hours=24)
AFTERCARE_WINDOW = timedelta(days=7)
GHOST_THRESHOLD = timedelta(days=7)


def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def classify_stage(
    client: Client,
    *,
    recent_inbound_count: int,
    now: datetime | None = None,
) -> Stage:
    """Return the `Stage` the fan should be in right now.

    Order of checks (first match wins):

    1. Handoff required → `HANDOFF`
    2. Active suppression → `PAUSED_SAFETY`
    3. Within OFFER_PENDING_WINDOW since last offer with no purchase since
       → `OFFER_PENDING`
    4. Recent purchase within AFTERCARE_WINDOW → `AFTERCARE`
    5. Older purchase → `REPEAT_READY`
    6. Inactive longer than GHOST_THRESHOLD → `GHOST`
    7. Otherwise driven by `recent_inbound_count`.
    """
    n = now or datetime.now(UTC)

    if client.handoff_required:
        return Stage.HANDOFF

    sup = _to_utc(client.suppression_until)
    if sup is not None and sup > n:
        return Stage.PAUSED_SAFETY

    last_offer = _to_utc(client.last_offer_at)
    last_purchase = _to_utc(client.last_purchase_at)

    if (
        last_offer is not None
        and (n - last_offer) <= OFFER_PENDING_WINDOW
        and (last_purchase is None or last_purchase < last_offer)
    ):
        return Stage.OFFER_PENDING

    if last_purchase is not None:
        if (n - last_purchase) <= AFTERCARE_WINDOW:
            return Stage.AFTERCARE
        return Stage.REPEAT_READY

    last_inbound = _to_utc(client.last_inbound_at)
    if last_inbound is not None and (n - last_inbound) >= GHOST_THRESHOLD:
        return Stage.GHOST

    if recent_inbound_count >= QUALIFY_MIN_INBOUND:
        return Stage.QUALIFY
    if recent_inbound_count >= WARMUP_MIN_INBOUND:
        return Stage.WARMUP
    return Stage.WELCOME


class JourneyEngine:
    """Stateless façade. Methods take `session` + `client`."""

    @staticmethod
    async def classify_and_persist(
        session: AsyncSession,
        *,
        client: Client,
        recent_inbound_count: int,
        now: datetime | None = None,
    ) -> tuple[Stage, bool]:
        """Compute the stage and persist it on the client row if changed.

        Returns `(stage, changed)` where `changed` is True iff the stored
        `current_stage` was different and got updated.

        Phase 3: when the stage changes, auto-enqueues proactive followups
        via `ProactiveEngine.on_stage_transition`.
        """
        old_stage = client.current_stage
        stage = classify_stage(client, recent_inbound_count=recent_inbound_count, now=now)
        changed = await update_stage(
            session,
            fan_id=client.fan_id,
            stage=stage,
            reason="journey_classify",
        )
        if changed:
            from sonya.scheduler.proactive import ProactiveEngine

            await ProactiveEngine.on_stage_transition(
                session,
                client=client,
                new_stage=stage.value,
                old_stage=old_stage,
                now=now,
            )
        return stage, changed


__all__ = [
    "AFTERCARE_WINDOW",
    "GHOST_THRESHOLD",
    "JourneyEngine",
    "OFFER_PENDING_WINDOW",
    "QUALIFY_MIN_INBOUND",
    "WARMUP_MIN_INBOUND",
    "classify_stage",
]

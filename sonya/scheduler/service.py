"""Async APScheduler wrapper + cadence policy.

The actual sending of a followup message is delegated to a callback so this
module stays independent of Telethon (and thus testable). `SchedulerService`
runs a single periodic tick that:

1. Picks up `due_followups` from the DB.
2. Builds the message text for each (`build_followup_message`).
3. Calls the supplied `send` callback with `(fan_id, text, followup_type)`.
4. Marks the row executed on success.

It also exposes `enqueue_*` helpers for convenience and `cancel_for_fan`
for the dialogue handler to call when a fan replies.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sonya.crm.classifier import FanTypeLite as FanType
from sonya.db.models import Client, Followup
from sonya.observability import EventType, write_event
from sonya.scheduler.proactive import ProactiveEngine
from sonya.scheduler.repository import (
    cancel_pending_for_fan,
    due_followups,
    enqueue_followup,
    mark_executed,
)

SendCallable = Callable[[int, str, str], Awaitable[bool]]
"""Signature: send(fan_id, text, followup_type) -> True if sent ok."""


@dataclass(frozen=True)
class CadenceConfig:
    """Tunables for the cadence engine. All durations are timedeltas."""

    # GHOST recovery: a fan classified GHOST gets one check-in this many days
    # after they went quiet (0 means immediately on first scheduler tick).
    ghost_recovery_after: timedelta = timedelta(days=7)
    # Aftercare: thank-you ping this long after a successful payment.
    aftercare_thanks_after: timedelta = timedelta(hours=24)
    # Aftercare second touch ("did you enjoy it?") follow-up.
    aftercare_checkin_after: timedelta = timedelta(days=3)
    # How often the scheduler tick runs (seconds).
    tick_interval_seconds: float = 60.0


def build_followup_message(*, fan_type: str | None, type_: str, name: str | None) -> str:
    """Render a default followup copy. Static, language-en, intentionally bland.

    The dialogue layer can override per fan (e.g. via knowledge), but the
    scheduler must always have a safe fallback so we never send empty.
    """
    salutation = f"Hey {name}" if name else "Hey"
    if type_ == "ghost_recovery":
        if fan_type == FanType.WHALE.value:
            return f"{salutation}, missed you 💜 anything you'd love me to make for you?"
        return f"{salutation}, haven't heard from you in a while — how's your week been?"
    if type_ == "aftercare_thanks":
        return f"{salutation}, just wanted to say thank you again 💜 hope you enjoyed it."
    if type_ == "aftercare_checkin":
        return f"{salutation}, was it everything you hoped for? would love to hear back."
    if type_ == "birthday":
        return f"{salutation}, happy birthday 🎂 hope you're being spoiled today."
    return f"{salutation}, thinking of you."


class SchedulerService:
    """Owns the AsyncIOScheduler and the periodic cadence tick."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        send: SendCallable,
        config: CadenceConfig | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._send = send
        self._config = config or CadenceConfig()
        self._sched = AsyncIOScheduler(timezone="UTC")
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._sched.add_job(
            self._tick,
            trigger="interval",
            seconds=self._config.tick_interval_seconds,
            id="cadence_tick",
            replace_existing=True,
        )
        self._sched.start()
        self._started = True
        logger.info("SchedulerService started (tick every {}s)", self._config.tick_interval_seconds)

    def shutdown(self) -> None:
        if not self._started:
            return
        try:
            self._sched.shutdown(wait=False)
        except Exception:  # pragma: no cover - shutdown best-effort
            logger.opt(exception=True).warning("SchedulerService shutdown failed")
        self._started = False

    async def _tick(self) -> None:
        """One pass: dispatch every followup that's due."""
        try:
            await self.run_once()
        except Exception:  # pragma: no cover - never let APS crash on a tick
            logger.opt(exception=True).error("Scheduler tick failed")

    async def run_once(self) -> int:
        """Process all currently-due followups. Returns number actually sent.

        Exposed (and `async`-friendly) for tests so we don't depend on APS.
        """
        async with self._session_factory() as session, session.begin():
            due = await due_followups(session, now=datetime.now(UTC))
            if not due:
                return 0
            sent = 0
            for row in due:
                handled = await self._dispatch_one(session, row)
                if handled:
                    sent += 1
            return sent

    async def _dispatch_one(self, session: AsyncSession, row: Followup) -> bool:
        client = await session.get(Client, row.fan_id)
        if client is None:
            await mark_executed(session, followup_id=row.id)
            return False

        # Phase 3: unified gate — cadence + timezone window.
        allowed, reason = ProactiveEngine.should_send_now(client)
        if not allowed:
            logger.info(
                "Proactive skip followup={} fan={} type={} reason={}",
                row.id,
                row.fan_id,
                row.type,
                reason,
            )
            # Timezone block → defer (don't cancel — we'll retry next tick).
            if "outside_send_window" in reason:
                await write_event(
                    session,
                    fan_id=row.fan_id,
                    event_type=EventType.FOLLOWUP_SKIPPED,
                    payload={
                        "followup_id": row.id,
                        "type": row.type,
                        "reason": reason,
                        "deferred": True,
                    },
                )
                return False

            # Hard cadence block (suppression, handoff, burst) → cancel.
            await write_event(
                session,
                fan_id=row.fan_id,
                event_type=EventType.FOLLOWUP_SKIPPED,
                payload={
                    "followup_id": row.id,
                    "type": row.type,
                    "reason": reason,
                },
            )
            row.cancelled = True
            tail = f"proactive_blocked:{reason}"
            row.note = f"{row.note}\n{tail}" if row.note else tail
            await session.flush()
            return False

        # Phase 3: grain-aware message building.
        template_ref = _extract_template_ref(row.note)
        text = ProactiveEngine.build_proactive_text(
            client=client,
            followup_type=row.type,
            template_ref=template_ref,
        )
        try:
            ok = await self._send(row.fan_id, text, row.type)
        except Exception:
            logger.opt(exception=True).error(
                "Followup send failed (fan={}, type={})", row.fan_id, row.type
            )
            ok = False
        if ok:
            await mark_executed(session, followup_id=row.id)
        return bool(ok)

    # ---- enqueue helpers (delegate to repository, but timezone-aware) ----

    async def enqueue_ghost_recovery(
        self, session: AsyncSession, *, fan_id: int, when: datetime | None = None
    ) -> Followup:
        when = when or datetime.now(UTC) + self._config.ghost_recovery_after
        return await enqueue_followup(
            session, fan_id=fan_id, type_="ghost_recovery", scheduled_at=when
        )

    async def enqueue_aftercare(self, session: AsyncSession, *, fan_id: int) -> list[Followup]:
        now = datetime.now(UTC)
        thanks = await enqueue_followup(
            session,
            fan_id=fan_id,
            type_="aftercare_thanks",
            scheduled_at=now + self._config.aftercare_thanks_after,
        )
        checkin = await enqueue_followup(
            session,
            fan_id=fan_id,
            type_="aftercare_checkin",
            scheduled_at=now + self._config.aftercare_checkin_after,
        )
        return [thanks, checkin]

    async def cancel_for_fan(
        self, session: AsyncSession, *, fan_id: int, reason: str = "replied"
    ) -> int:
        return await cancel_pending_for_fan(session, fan_id=fan_id, reason=reason)


def _extract_template_ref(note: str | None) -> str | None:
    """Parse `template_ref=X` from the followup row's note field."""
    if not note:
        return None
    for part in note.split():
        if part.startswith("template_ref="):
            val = part[len("template_ref=") :]
            return val if val and val != "None" else None
    return None


async def _noop_send(fan_id: int, text: str, type_: str) -> bool:  # pragma: no cover
    """Default send callable: log only. Useful in DRY_RUN."""
    logger.info("[scheduler dry-run] fan={} type={} text={!r}", fan_id, type_, text)
    await asyncio.sleep(0)
    return True

"""ProactiveEngine — orchestrates stage-based proactive sends.

Responsibilities:
1. On stage transition → enqueue followups per the timer matrix.
2. On fan reply → cancel all pending followups for that fan.
3. On tick → dispatch due followups with timezone + cadence gate.
4. Track attempt counts per fan/stage so multi-step sequences (ghost D1/D2/D3)
   progress correctly.

The engine wraps the existing `SchedulerService` tick loop but adds:
- Timezone-aware send window (no sends outside 09:00-22:00 fan-local).
- Grain/archetype-aware message rendering (via the library selectors).
- Stage-specific message generation (LLM or template-based).
- Attempt tracking for multi-step sequences.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from sonya.cadence import CadenceEngine
from sonya.db.models import Client, Followup
from sonya.library import pick_archetype, pick_grain
from sonya.library.selectors import crm_stage_to_rail_id
from sonya.observability import EventType, write_event
from sonya.scheduler.repository import cancel_pending_for_fan, enqueue_followup
from sonya.scheduler.timer_matrix import (
    get_timers,
    is_in_send_window,
)

# How long to defer a proactive send when the fan is outside the send window.
# The scheduler will re-check on the next tick.
TIMEZONE_DEFER_HOURS = 2

# Maximum number of proactive attempts per stage before giving up.
MAX_GHOST_ATTEMPTS = 3
MAX_DRIP_ATTEMPTS = 2


def _fan_local_hour(timezone_guess: str | None) -> int | None:
    """Best-effort fan local hour for timezone gating."""
    if not timezone_guess:
        return None
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        tz = ZoneInfo(timezone_guess)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None
    return datetime.now(tz).hour


class ProactiveEngine:
    """Stateless engine for proactive message scheduling."""

    @staticmethod
    async def on_stage_transition(
        session: AsyncSession,
        *,
        client: Client,
        new_stage: str,
        old_stage: str | None = None,
        now: datetime | None = None,
    ) -> list[Followup]:
        """Enqueue followups when a fan transitions to a new stage.

        Called by JourneyEngine after persisting the stage change. Returns
        the list of newly-enqueued followup rows (for logging / events).
        """
        n = now or datetime.now(UTC)

        # Cancel any pending followups from the old stage.
        if old_stage and old_stage != new_stage:
            await cancel_pending_for_fan(
                session, fan_id=client.fan_id, reason=f"stage_transition:{new_stage}"
            )

        # Map CRM stage string to rail stage id for timer lookup.
        rail_id = crm_stage_to_rail_id(new_stage) or new_stage.upper()
        timers = get_timers(rail_id)
        if not timers:
            return []

        enqueued: list[Followup] = []
        for i, rule in enumerate(timers):
            scheduled_at = n + rule.after
            row = await enqueue_followup(
                session,
                fan_id=client.fan_id,
                type_=rule.action,
                scheduled_at=scheduled_at,
                note=f"stage={new_stage} attempt={i} template_ref={rule.template_ref}",
            )
            enqueued.append(row)

        if enqueued:
            await write_event(
                session,
                fan_id=client.fan_id,
                event_type=EventType.ACTION_SELECTED,
                payload={
                    "action": "proactive_enqueue",
                    "stage": new_stage,
                    "rail_id": rail_id,
                    "followups_count": len(enqueued),
                    "timers": [
                        {"action": r.action, "after_h": r.after.total_seconds() / 3600}
                        for r in timers[: len(enqueued)]
                    ],
                },
            )

        return enqueued

    @staticmethod
    async def on_fan_replied(
        session: AsyncSession,
        *,
        fan_id: int,
    ) -> int:
        """Cancel all pending proactive followups when a fan replies.

        Returns number of cancelled followups.
        """
        return await cancel_pending_for_fan(session, fan_id=fan_id, reason="fan_replied")

    @staticmethod
    def should_send_now(
        client: Client,
        *,
        proactive_allowed_by_safety: bool = True,
    ) -> tuple[bool, str]:
        """Pre-dispatch gate: cadence + timezone check.

        Returns (allowed, reason). Reason is empty string when allowed.
        """
        # Cadence gate (suppression, handoff, burst limit, operator pause).
        cadence = CadenceEngine.should_proactively_send(
            client, proactive_allowed_by_safety=proactive_allowed_by_safety
        )
        if not cadence.allowed:
            return False, cadence.reason

        # Timezone gate.
        hour = _fan_local_hour(client.timezone_guess)
        if not is_in_send_window(hour):
            return False, f"outside_send_window(hour={hour})"

        return True, ""

    @staticmethod
    def build_proactive_text(
        *,
        client: Client,
        followup_type: str,
        template_ref: str | None = None,
    ) -> str:
        """Build the proactive message text, grain-aware.

        Uses the fan's archetype + time-of-day grain to pick appropriate tone.
        Falls back to static copy when no better option is available.
        """
        name = client.known_name or client.first_name
        salutation = f"hey {name}" if name else "hey"

        # Pick grain + archetype for tone calibration.
        hour = _fan_local_hour(client.timezone_guess)
        archetype = pick_archetype(fan_type=client.fan_type)
        grain = pick_grain(fan_local_hour=hour, archetype=archetype)

        # Type-specific message templates (grain-calibrated).
        if "ghost_recovery" in followup_type or followup_type.startswith("ghost"):
            return _ghost_message(salutation, grain.id, followup_type, client.fan_type)
        if "welcome_drip" in followup_type:
            return _welcome_drip_message(salutation, grain.id, followup_type)
        if "aftercare" in followup_type:
            return _aftercare_message(salutation, followup_type)
        if "storybait" in followup_type or "cooling" in followup_type:
            return _storybait_message(salutation, grain.id)
        if "anchor" in followup_type:
            return _anchor_message(salutation, grain.id)
        if "ppv" in followup_type or "bundle" in followup_type:
            return _ppv_followup_message(salutation)
        if "repeat" in followup_type or "new_ppv" in followup_type:
            return _repeat_cycle_message(salutation, grain.id)

        return f"{salutation}, thinking of you)"


# --- Message generators (grain-calibrated, in-character) ---


def _ghost_message(salutation: str, grain_id: str, type_: str, fan_type: str | None) -> str:
    """Ghost recovery messages escalate gently over D1→D2→D3."""
    if fan_type and fan_type.upper() in ("B1", "WHALE", "VIP"):
        if "D1" in type_:
            return f"{salutation}, пропала ты куда-то) скучаю"
        if "D2" in type_:
            return f"{salutation}, всё хорошо? давно не слышала тебя 💜"
        return f"{salutation}, напиши когда будешь — я тут)"
    if "D1" in type_:
        if grain_id in ("G1", "G2"):
            return f"{salutation}, как ты? давно не писал)"
        if grain_id in ("G3", "G4"):
            return f"{salutation}, эй) ты где пропал?"
        return f"{salutation}, haven't heard from you in a while — how's your week?"
    if "D2" in type_:
        if grain_id in ("G1", "G2", "G3", "G4"):
            return f"{salutation}, вспомнила про тебя сегодня) напиши что-нибудь"
        return f"{salutation}, thought of you today — send me something)"
    # D3
    if grain_id in ("G1", "G2", "G3", "G4"):
        return f"{salutation}, ладно, я тут если что) не пропадай"
    return f"{salutation}, i'm here when you're ready — don't be a stranger)"


def _welcome_drip_message(salutation: str, grain_id: str, type_: str) -> str:
    """Welcome drip: warm + curious, never pushy."""
    if "D1" in type_:
        if grain_id in ("G1", "G2", "G3", "G4"):
            return f"{salutation}) расскажи о себе что-нибудь — мне правда интересно"
        return f"{salutation}) tell me something about yourself — i'm genuinely curious"
    # D3
    if grain_id in ("G1", "G2", "G3", "G4"):
        return (
            f"{salutation}, слушай, я тут подумала — тебе нравится фоткаться или больше смотришь?"
        )
    return f"{salutation}, was thinking — do you like taking pics yourself or more of a viewer?"


def _aftercare_message(salutation: str, type_: str) -> str:
    if "thanks" in type_:
        return f"{salutation}, ещё раз спасибо 💜 надеюсь понравилось"
    return f"{salutation}, ну как — всё как ожидал? хочу фидбэк)"


def _storybait_message(salutation: str, grain_id: str) -> str:
    if grain_id in ("G1", "G2"):
        return f"{salutation}, мне сегодня снилась какая-то дичь) а тебе снятся сны?"
    if grain_id in ("G3", "G4"):
        return f"{salutation}, вечер) чем занят? я тут фильм смотрю — не могу определиться)"
    return f"{salutation}, random q — what's the last thing that made you laugh out loud?"


def _anchor_message(salutation: str, grain_id: str) -> str:
    if grain_id in ("G1", "G2", "G3", "G4"):
        return f"{salutation}, у меня тут настроение что-то новое попробовать) а у тебя?"
    return f"{salutation}, feeling adventurous today — what about you?"


def _ppv_followup_message(salutation: str) -> str:
    return f"{salutation}, видел(а) что я отправила? просто хотела уточнить)"


def _repeat_cycle_message(salutation: str, grain_id: str) -> str:
    if grain_id in ("G1", "G2", "G3", "G4"):
        return f"{salutation}, кое-что новое есть — думаю тебе понравится)"
    return f"{salutation}, got something new — think you'll like it)"


__all__ = [
    "MAX_DRIP_ATTEMPTS",
    "MAX_GHOST_ATTEMPTS",
    "ProactiveEngine",
    "TIMEZONE_DEFER_HOURS",
]

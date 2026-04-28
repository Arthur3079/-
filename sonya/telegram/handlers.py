"""Telethon incoming-message handlers.

The handler is intentionally **thin**: it filters the event, persists the
incoming message to the DB, asks `DialogueService` for a reply, and (if any)
sends it through the safe Telegram I/O wrapper. All business logic — safety,
LLM, retrieval, prompt assembly, fallbacks — lives in `sonya.dialogue`.

Concurrency:
- Each fan_id has its own `asyncio.Lock` (`PerFanLockRegistry`). Two messages
  from the same fan are processed sequentially, never in parallel.
- A `Debouncer` collapses bursts of short messages into one reply: each
  incoming bumps a generation counter; only the coroutine whose generation
  is still latest after the quiet window proceeds.

All outbound I/O goes through `safe_respond` / `safe_typing_action`, which
absorb FloodWait / RPCError so a rate-limit can't kill the handler.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from loguru import logger
from telethon import TelegramClient, events
from telethon.tl.types import (
    MessageMediaDocument,
    MessageMediaPhoto,
    User,
)

from sonya.config import Settings
from sonya.crm.repository import (
    get_or_create_client,
    mark_inbound_seen,
    mark_outbound_sent,
    save_message,
)
from sonya.db.models import Client, MessageDirection, MessageMediaType
from sonya.db.session import async_session_factory
from sonya.dialogue import DialogueResult, DialogueService, SkipReason
from sonya.humanizer import (
    calculate_timing,
    interruptible_sleep,
    sleep_awareness_interruptible,
    sleep_typing_interruptible,
)
from sonya.knowledge import KnowledgeIndex
from sonya.llm.backend import LLMBackend
from sonya.observability import EventType, write_event
from sonya.runtime import Debouncer, PerFanLockRegistry, safe_respond, safe_typing_action


def register_handlers(
    client: TelegramClient,
    settings: Settings,
    *,
    backend: LLMBackend | None = None,
    knowledge: KnowledgeIndex | None = None,
) -> DialogueService:
    """Register the NewMessage handler and return the constructed `DialogueService`.

    Returning the service makes it easy for tests / future admin tooling to
    poke at the same orchestrator the handler is using.
    """
    service = DialogueService(settings=settings, backend=backend, knowledge=knowledge)
    locks = PerFanLockRegistry()
    debouncer = Debouncer(quiet_period=settings.incoming_debounce_seconds)

    @client.on(events.NewMessage(incoming=True))
    async def _on_incoming(event: events.NewMessage.Event) -> None:
        await _handle_incoming(
            event,
            settings=settings,
            service=service,
            locks=locks,
            debouncer=debouncer,
        )

    return service


async def _handle_incoming(
    event: events.NewMessage.Event,
    *,
    settings: Settings,
    service: DialogueService,
    locks: PerFanLockRegistry,
    debouncer: Debouncer,
) -> None:
    sender = await event.get_sender()
    if not isinstance(sender, User):
        return
    if sender.bot:
        return
    if sender.is_self:
        return
    if not event.is_private:
        return

    text = event.raw_text or ""
    media_type = _detect_media_type(event)
    logger.info(
        "Incoming PM from {} (id={}): media={} text={!r}",
        getattr(sender, "username", None) or sender.id,
        sender.id,
        media_type.value,
        text[:120],
    )

    # Persist immediately so history reflects this turn even if we end up
    # debouncing the reply.
    factory = async_session_factory()
    async with factory() as session, session.begin():
        await get_or_create_client(
            session,
            fan_id=sender.id,
            username=sender.username,
            first_name=sender.first_name,
            last_name=sender.last_name,
        )
        msg_ts = event.message.date or datetime.now(UTC)
        await save_message(
            session,
            fan_id=sender.id,
            tg_message_id=event.message.id,
            direction=MessageDirection.INCOMING,
            content=text,
            media_type=media_type,
            timestamp=msg_ts,
        )
        await mark_inbound_seen(session, fan_id=sender.id, at=msg_ts)
        await write_event(
            session,
            fan_id=sender.id,
            event_type=EventType.INBOUND_RECEIVED,
            payload={
                "media": media_type.value,
                "len": len(text),
                "tg_message_id": event.message.id,
            },
            timestamp=msg_ts,
        )

    generation = debouncer.bump(sender.id)
    is_latest = await debouncer.wait_for_quiet(sender.id, generation)
    if not is_latest:
        logger.info(
            "Debounced: a newer message arrived for fan_id={} (gen={}); skipping.",
            sender.id,
            generation,
        )
        return

    async with locks.hold(sender.id):
        # Re-check after taking the lock — another holder for the same fan
        # might have just answered and bumped the generation again.
        if debouncer.current_generation(sender.id) != generation:
            logger.info(
                "Debounced under lock: a newer message arrived for fan_id={}; skipping.",
                sender.id,
            )
            return

        async with factory() as session, session.begin():
            client_obj = await _reload_client(session, fan_id=sender.id)
            if client_obj is None:
                logger.error("Client row missing for fan_id={} (race?); skipping.", sender.id)
                return
            if client_obj.is_paused:
                logger.info(
                    "Fan {} is paused ({}); operator handles this turn.",
                    sender.id,
                    client_obj.paused_reason or "no reason",
                )
                await write_event(
                    session,
                    fan_id=sender.id,
                    event_type=EventType.INBOUND_SKIPPED_PAUSED,
                    payload={"reason": client_obj.paused_reason},
                )
                return
            # Fan replied → cancel any pending check-ins (ghost recovery,
            # aftercare). Best-effort; don't fail the turn on errors.
            try:
                from sonya.scheduler import cancel_pending_for_fan

                cancelled = await cancel_pending_for_fan(
                    session, fan_id=sender.id, reason="replied"
                )
                if cancelled:
                    logger.info(
                        "Cancelled {} pending followup(s) for fan {}",
                        cancelled,
                        sender.id,
                    )
            except Exception:  # pragma: no cover - never block the dialogue
                logger.opt(exception=True).warning(
                    "Failed to cancel pending followups for fan {}", sender.id
                )
            result = await service.handle_incoming(session, client=client_obj, text=text)

        # Cooperative cancellation: if a newer message arrives while we're
        # mid-typing, abandon this send so the newer turn can take over.
        def _cancel() -> bool:
            return debouncer.current_generation(sender.id) != generation

        await _send_reply(event, result, settings=settings, cancel=_cancel)


async def _reload_client(session, *, fan_id: int) -> Client | None:
    from sqlalchemy import select

    res = await session.execute(select(Client).where(Client.fan_id == fan_id))
    return res.scalar_one_or_none()


async def _send_reply(
    event: events.NewMessage.Event,
    result: DialogueResult,
    *,
    settings: Settings,
    cancel: Callable[[], bool] | None = None,
) -> None:
    """Apply humanizer timing and send each bubble via safe wrappers.

    `cancel` is polled during humanizer sleeps; when it returns True, we stop
    sending remaining bubbles (a newer incoming message will own the next reply).
    """
    if not result.should_send:
        if result.skipped_reason is not SkipReason.NONE:
            logger.info(
                "No reply sent (reason={}, handoff={}, flags={}, intent={}, fan_type={}).",
                result.skipped_reason.value,
                result.handoff_required,
                ",".join(result.safety_flags) or "-",
                result.intent or "-",
                result.fan_type or "-",
            )
        return

    bubbles = result.send_bubbles
    if not bubbles:
        return

    if settings.dry_run:
        for i, b in enumerate(bubbles, start=1):
            logger.warning(
                "DRY_RUN=true — пропускаю отправку bubble {}/{}: {!r}",
                i,
                len(bubbles),
                b,
            )
        factory = async_session_factory()
        async with factory() as session, session.begin():
            await write_event(
                session,
                fan_id=event.sender_id,
                event_type=EventType.DRY_RUN_OUTPUT,
                payload={
                    "bubbles": list(bubbles),
                    "intent": result.intent,
                    "fan_type": result.fan_type,
                },
            )
        return

    factory = async_session_factory()
    for i, bubble in enumerate(bubbles, start=1):
        timing = calculate_timing(bubble)

        if settings.enable_humanizer:
            ok = await sleep_awareness_interruptible(timing, cancel=cancel)
            if not ok:
                _log_cancel(event.sender_id, i, len(bubbles))
                return
            async with safe_typing_action(event):
                ok = await sleep_typing_interruptible(timing, cancel=cancel)
                if not ok:
                    _log_cancel(event.sender_id, i, len(bubbles))
                    return
                sent = await safe_respond(
                    event,
                    bubble,
                    max_flood_wait=settings.telegram_max_flood_wait_seconds,
                )
        else:
            sent = await safe_respond(
                event,
                bubble,
                max_flood_wait=settings.telegram_max_flood_wait_seconds,
            )

        if sent is None:
            # safe_respond logged the reason; skip persistence.
            continue

        async with factory() as session, session.begin():
            await save_message(
                session,
                fan_id=event.sender_id,
                tg_message_id=getattr(sent, "id", None),
                direction=MessageDirection.OUTGOING,
                content=bubble,
            )
            counter = await mark_outbound_sent(session, fan_id=event.sender_id)
            await write_event(
                session,
                fan_id=event.sender_id,
                event_type=EventType.MESSAGE_SENT,
                payload={
                    "tg_message_id": getattr(sent, "id", None),
                    "len": len(bubble),
                    "bubble_index": i,
                    "consecutive_outbound": counter,
                },
            )

        # Inter-bubble pause (skip after the last one).
        if i < len(bubbles) and settings.enable_humanizer:
            ok = await interruptible_sleep(settings.inter_bubble_delay_seconds, cancel=cancel)
            if not ok:
                _log_cancel(event.sender_id, i + 1, len(bubbles))
                return


def _log_cancel(fan_id: int, bubble_idx: int, total: int) -> None:
    logger.info(
        "Humanizer cancelled mid-reply for fan_id={}: bubble {}/{} dropped "
        "(newer incoming arrived).",
        fan_id,
        bubble_idx,
        total,
    )


def _detect_media_type(event: events.NewMessage.Event) -> MessageMediaType:
    msg = event.message
    if not msg.media:
        return MessageMediaType.TEXT
    if msg.voice:
        return MessageMediaType.VOICE
    if msg.video_note:
        return MessageMediaType.VIDEO_NOTE
    if msg.video:
        return MessageMediaType.VIDEO
    if msg.photo or isinstance(msg.media, MessageMediaPhoto):
        return MessageMediaType.PHOTO
    if msg.sticker:
        return MessageMediaType.STICKER
    if msg.document or isinstance(msg.media, MessageMediaDocument):
        return MessageMediaType.DOCUMENT
    return MessageMediaType.OTHER

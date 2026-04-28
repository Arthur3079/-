"""DialogueService — single entry point for «one incoming → one reply».

Sequence:

    1. evaluate_incoming(text)              # safety pre-check
       └─ if blocked: return DialogueResult with safe canned reply
    2. load Client, history, facts          # CRM context
    3. knowledge.retrieve(query, fan_type)  # if index is provided
    4. build system prompt + history        # prompt assembly
    5. backend.generate                     # LLM call (with fallback)
    6. evaluate_reply(text)                 # safety post-check
       └─ if blocked: return DialogueResult with safe canned reply
    7. return DialogueResult with reply_text

The service is fully unit-testable without Telethon: pass a fake LLMBackend
(any object with `.generate(messages, *, fan_id) -> str` and `.aclose()`),
pass an in-memory async sqlite session, and you can drive every branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.cadence import CadenceEngine
from sonya.config import Settings
from sonya.crm.classifier import classify_fan
from sonya.crm.facts import facts_dict
from sonya.crm.repository import count_inbound_messages
from sonya.db.models import Client
from sonya.dialogue.bubbles import split_into_bubbles
from sonya.dialogue.intent import Intent, classify_intent
from sonya.dialogue.result import DialogueResult, SkipReason
from sonya.journey.engine import JourneyEngine
from sonya.journey.next_best_action import NextAction, select_next_best_action
from sonya.knowledge import KnowledgeIndex
from sonya.library import (
    pick_archetype,
    pick_few_shot,
    pick_grain,
    render_persona_block,
)
from sonya.library.selectors import (
    crm_stage_to_rail_id,
    render_few_shot_block,
)
from sonya.llm.backend import LLMBackend
from sonya.llm.client import ChatMessage
from sonya.llm.conversation import (
    fetch_history,
    history_to_chat_messages,
)
from sonya.llm.prompts import (
    build_system_prompt,
    render_client_card,
    render_facts_block,
    render_orchestrator_hints,
)
from sonya.observability import EventType, write_event
from sonya.safety import SafetyAction, SafetyEngine, evaluate_reply
from sonya.safety.hardening import MAX_REGEN_ATTEMPTS, SafetyHardening
from sonya.sales.engine import RecommendOutcome, build_recommendation

FALLBACK_REPLY = "hey, give me a sec — back to you in a min 💕"


def _fan_local_hour(timezone_guess: str | None) -> int | None:
    """Best-effort fan-local hour for grain selection.

    `clients.timezone_guess` is a free-form IANA TZ string (e.g. "Europe/Madrid").
    When unset, malformed, or pointing at an unknown zone, return `None` so
    the grain selector falls back to the archetype/default rather than
    guessing UTC.
    """
    if not timezone_guess:
        return None
    try:
        tz = ZoneInfo(timezone_guess)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return datetime.now(tz).hour


@dataclass
class DialogueService:
    """Stateless orchestrator. Holds settings + optional LLM/knowledge handles."""

    settings: Settings
    backend: LLMBackend | None = None
    knowledge: KnowledgeIndex | None = None

    async def handle_incoming(
        self,
        session: AsyncSession,
        *,
        client: Client,
        text: str,
    ) -> DialogueResult:
        """Produce a `DialogueResult` for one incoming message from `client`.

        The caller (handler) is responsible for having already persisted the
        incoming message to the DB before calling this — `fetch_history` will
        then see it.
        """
        if not text or not text.strip():
            # We don't synthesise replies for empty / pure-media incoming in
            # this MVP; future media handling will populate `text` from a
            # voice/photo description.
            return DialogueResult(reply_text=None, skipped_reason=SkipReason.EMPTY_INCOMING)

        outcome = await SafetyEngine.precheck(session, client=client, text=text)
        pre = outcome.verdict
        if pre.action is SafetyAction.DROP_SILENTLY:
            return DialogueResult(
                reply_text=None,
                skipped_reason=SkipReason.SAFETY_PRE_BLOCK,
                handoff_required=pre.handoff_required,
                safety_flags=pre.reasons,
            )
        if not pre.allowed:
            return DialogueResult(
                reply_text=pre.safe_reply,
                skipped_reason=SkipReason.SAFETY_PRE_BLOCK,
                handoff_required=pre.handoff_required,
                safety_flags=pre.reasons,
            )

        intent_res = classify_intent(text)
        fan_res = await classify_fan(session, client=client)
        logger.info(
            "Dialogue context fan_id={} intent={} ({} conf) fan_type={} ({})",
            client.fan_id,
            intent_res.intent.value,
            intent_res.confidence,
            fan_res.fan_type.value,
            ",".join(fan_res.reasons) or "-",
        )

        inbound_count = await count_inbound_messages(session, fan_id=client.fan_id)
        stage, _stage_changed = await JourneyEngine.classify_and_persist(
            session, client=client, recent_inbound_count=inbound_count
        )

        cadence_reply = CadenceEngine.should_reply(client)
        cadence_offer = CadenceEngine.should_offer_sales(
            client,
            stage=stage,
            sales_allowed_by_safety=pre.effective_sales_allowed,
            recent_inbound_count=inbound_count,
        )
        nba = select_next_best_action(
            stage=stage,
            safety_verdict=pre,
            cadence_offer=cadence_offer,
            cadence_reply=cadence_reply,
            intent=intent_res.intent,
        )
        await write_event(
            session,
            fan_id=client.fan_id,
            event_type=EventType.ACTION_SELECTED,
            payload={
                "action": nba.action.value,
                "reason": nba.reason,
                "stage": stage.value,
                "intent": intent_res.intent.value,
                "fan_type": fan_res.fan_type.value,
                "inbound_count": inbound_count,
                "cadence_offer_allowed": cadence_offer.allowed,
                "cadence_offer_reason": cadence_offer.reason,
                "cadence_reply_allowed": cadence_reply.allowed,
                "cadence_reply_reason": cadence_reply.reason,
            },
        )

        if nba.action is NextAction.NO_REPLY:
            return DialogueResult(
                reply_text=None,
                skipped_reason=SkipReason.SAFETY_PRE_BLOCK,
                handoff_required=client.handoff_required,
                safety_flags=pre.reasons,
                intent=intent_res.intent.value,
                fan_type=fan_res.fan_type.value,
            )

        if self.backend is None:
            # Smoke-only path: no LLM configured. Stub-echo, no context, no LLM.
            stub = f"[stub] received: {text}"
            return DialogueResult(
                reply_text=stub,
                skipped_reason=SkipReason.LLM_NOT_CONFIGURED,
                safety_flags=pre.reasons,
                intent=intent_res.intent.value,
                fan_type=fan_res.fan_type.value,
            )

        try:
            llm_text, used_files = await self._call_llm(
                session,
                client=client,
                text=text,
                intent=intent_res.intent,
                fan_type=fan_res.fan_type.value,
            )
        except Exception:  # noqa: BLE001
            logger.exception("DialogueService: LLM call failed; using fallback.")
            return DialogueResult(
                reply_text=FALLBACK_REPLY,
                skipped_reason=SkipReason.LLM_FAILED,
                safety_flags=pre.reasons,
                intent=intent_res.intent.value,
                fan_type=fan_res.fan_type.value,
            )

        if not llm_text or not llm_text.strip():
            return DialogueResult(
                reply_text=FALLBACK_REPLY,
                skipped_reason=SkipReason.EMPTY_REPLY,
                safety_flags=pre.reasons,
                intent=intent_res.intent.value,
                fan_type=fan_res.fan_type.value,
            )

        post = evaluate_reply(
            llm_text,
            incoming_text=text,
            fan_name=client.known_name or client.first_name,
            fan_language=client.language,
        )
        if not post.allowed:
            # Phase 6: Regenerate loop — retry LLM with corrective nudge.
            regen_text = await self._regenerate_loop(
                session,
                client=client,
                text=text,
                intent=intent_res.intent,
                fan_type=fan_res.fan_type.value,
                blocked_reasons=post.reasons,
            )
            if regen_text is not None:
                llm_text = regen_text
            else:
                logger.warning(
                    "Safety post-block fan_id={} reasons={} severity={} handoff={}",
                    client.fan_id,
                    ",".join(post.reasons),
                    post.severity.value,
                    post.handoff_required,
                )
                # Phase 6: Check escalation matrix.
                await SafetyHardening.maybe_escalate_and_handoff(
                    session,
                    client=client,
                    current_flags=post.reasons,
                )
                return DialogueResult(
                    reply_text=post.safe_reply,
                    skipped_reason=SkipReason.SAFETY_POST_BLOCK,
                    handoff_required=post.handoff_required,
                    safety_flags=tuple(list(pre.reasons) + list(post.reasons)),
                    intent=intent_res.intent.value,
                    fan_type=fan_res.fan_type.value,
                )

        clean_text = llm_text.strip()
        bubbles = list(split_into_bubbles(clean_text, max_bubbles=self.settings.max_reply_bubbles))

        # Sales offer (deterministic, after LLM): only if NextBestAction
        # picked REPLY_WITH_OFFER (cadence + safety + stage all green).
        recommendation: RecommendOutcome | None = None
        if nba.action is NextAction.REPLY_WITH_OFFER:
            recommendation = await self._maybe_recommend(
                session,
                client=client,
                intent=intent_res.intent,
                fan_type_lite=fan_res.fan_type.value,
            )
        offered_set_code: str | None = None
        invoice_payload: str | None = None
        if recommendation is not None:
            offered_set_code = recommendation.content_set.code
            invoice_payload = recommendation.invoice_payload
            cta_bubble = recommendation.cta
            if cta_bubble:
                bubbles.append(cta_bubble)

        return DialogueResult(
            reply_text=clean_text,
            skipped_reason=SkipReason.NONE,
            handoff_required=False,
            safety_flags=pre.reasons,
            intent=intent_res.intent.value,
            fan_type=fan_res.fan_type.value,
            used_knowledge=used_files,
            bubbles=tuple(bubbles),
            offered_set_code=offered_set_code,
            invoice_payload=invoice_payload,
        )

    async def _maybe_recommend(
        self,
        session: AsyncSession,
        *,
        client: Client,
        intent: Intent,
        fan_type_lite: str,
    ) -> RecommendOutcome | None:
        try:
            return await build_recommendation(
                session,
                fan_id=client.fan_id,
                intent=intent,
                fan_type_lite=fan_type_lite,
                fan_type_fine=client.fan_type,
                settings=self.settings,
            )
        except Exception:  # pragma: no cover - never block dialogue
            logger.opt(exception=True).warning(
                "Sales recommendation failed for fan_id={}", client.fan_id
            )
            return None

    # ---------- helpers ----------

    async def _call_llm(
        self,
        session: AsyncSession,
        *,
        client: Client,
        text: str,
        intent: Intent,
        fan_type: str,
    ) -> tuple[str, tuple[str, ...]]:
        """Run the LLM. Returns `(reply_text, used_knowledge_files)`."""
        assert self.backend is not None  # guarded by caller
        backend = self.backend

        history = await fetch_history(
            session, fan_id=client.fan_id, limit=self.settings.llm_history_limit
        )
        chat = history_to_chat_messages(history)

        card = render_client_card(client)

        facts = await facts_dict(session, fan_id=client.fan_id)
        facts_block = render_facts_block(facts)

        snippets: list[str] = []
        used_files: list[str] = []
        if self.knowledge is not None and self.knowledge.chunk_count > 0:
            retrieved = self.knowledge.retrieve(
                text,
                max_chunks=self.settings.knowledge_max_snippets,
                max_chars=self.settings.knowledge_max_chars,
                fan_type=fan_type,
                intent=intent.value,
            )
            for r in retrieved:
                snippets.append(r.text)
                used_files.append(r.file_id)
            if used_files:
                logger.info(
                    "Knowledge retrieval fan_id={} intent={} fan_type={} used files: {}",
                    client.fan_id,
                    intent.value,
                    fan_type,
                    ", ".join(used_files),
                )

        hints = render_orchestrator_hints(intent=intent.value, fan_type=fan_type)

        # Phase 2: pick library-driven voice + few-shot examples for THIS turn.
        # `client.fan_type` stores the fine-grained archetype code (A1..G3) set
        # by the L2 classifier / operator override; `fan_type` (the local
        # parameter from `classify_fan`) is the coarse label
        # (newcomer/regular/whale/ghost/risky). The fine-grained code wins
        # when present; the coarse label is the fallback for fresh fans.
        # `pick_grain` puts time-of-day ahead of archetype primary_grain, so
        # passing the archetype here just acts as the fallback when the fan's
        # timezone is unknown.
        archetype = pick_archetype(fan_type=fan_type, explicit_id=client.fan_type)
        fan_local_hour = _fan_local_hour(client.timezone_guess)
        grain = pick_grain(fan_local_hour=fan_local_hour, archetype=archetype)
        rail_stage_id = crm_stage_to_rail_id(client.current_stage)
        persona_block = render_persona_block(
            grain=grain, archetype=archetype, stage_id=rail_stage_id
        )
        few_shot_bundle = pick_few_shot(
            stage_id=rail_stage_id,
            fan_type_id=archetype.id,
            grain_id=grain.id,
        )
        few_shot_block = render_few_shot_block(few_shot_bundle)

        system_prompt = build_system_prompt(
            client_card=card or None,
            facts_block=facts_block or None,
            knowledge_snippets=snippets or None,
            orchestrator_hints=hints or None,
            persona_block=persona_block or None,
            few_shot_block=few_shot_block or None,
        )

        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=system_prompt),
            *chat,
        ]
        reply = await backend.generate(messages, fan_id=client.fan_id)
        return reply, tuple(used_files)

    async def _regenerate_loop(
        self,
        session: AsyncSession,
        *,
        client: Client,
        text: str,
        intent: Intent,
        fan_type: str,
        blocked_reasons: tuple[str, ...],
    ) -> str | None:
        """Phase 6: Retry LLM up to MAX_REGEN_ATTEMPTS with corrective nudge.

        Returns the clean text if a retry passes safety, or None if all retries fail.
        """
        if self.backend is None:
            return None

        nudge = SafetyHardening.build_regen_nudge(blocked_reasons)

        for attempt in range(MAX_REGEN_ATTEMPTS):
            try:
                regen_text, _ = await self._call_llm(
                    session,
                    client=client,
                    text=text,
                    intent=intent,
                    fan_type=fan_type,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Regen attempt {}/{} LLM failed for fan_id={}",
                    attempt + 1,
                    MAX_REGEN_ATTEMPTS,
                    client.fan_id,
                )
                continue

            if not regen_text or not regen_text.strip():
                continue

            post = evaluate_reply(
                regen_text,
                incoming_text=text,
                fan_name=client.known_name or client.first_name,
                fan_language=client.language,
            )
            if post.allowed:
                logger.info(
                    "Regen succeeded attempt={}/{} fan_id={}",
                    attempt + 1,
                    MAX_REGEN_ATTEMPTS,
                    client.fan_id,
                )
                await write_event(
                    session,
                    fan_id=client.fan_id,
                    event_type=EventType.SAFETY_FLAGGED,
                    payload={
                        "stage": "regen_success",
                        "attempt": attempt + 1,
                        "original_reasons": list(blocked_reasons),
                    },
                )
                return regen_text

            logger.debug(
                "Regen attempt {}/{} still blocked: {}",
                attempt + 1,
                MAX_REGEN_ATTEMPTS,
                ",".join(post.reasons),
            )

        # All attempts failed.
        await write_event(
            session,
            fan_id=client.fan_id,
            event_type=EventType.SAFETY_FLAGGED,
            payload={
                "stage": "regen_exhausted",
                "attempts": MAX_REGEN_ATTEMPTS,
                "original_reasons": list(blocked_reasons),
                "nudge": nudge,
            },
        )
        return None

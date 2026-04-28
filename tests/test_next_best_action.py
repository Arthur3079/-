"""Tests for `select_next_best_action` decision precedence."""

from __future__ import annotations

import pytest

from sonya.cadence import CadenceVerdict
from sonya.dialogue.intent import Intent
from sonya.journey import Stage
from sonya.journey.next_best_action import NextAction, select_next_best_action
from sonya.safety import SafetyAction, SafetySeverity, SafetyVerdict


def _verdict(
    *,
    allowed: bool = True,
    action: SafetyAction = SafetyAction.ALLOW,
    severity: SafetySeverity = SafetySeverity.NONE,
    handoff: bool = False,
    safe_reply: str | None = None,
) -> SafetyVerdict:
    return SafetyVerdict(
        allowed=allowed,
        severity=severity,
        action=action,
        reasons=(),
        safe_reply=safe_reply,
        handoff_required=handoff,
    )


_OFFER_OK = CadenceVerdict(allowed=True)
_OFFER_BAD = CadenceVerdict(allowed=False, reason="below_min_inbound")
_REPLY_OK = CadenceVerdict(allowed=True)
_REPLY_BAD = CadenceVerdict(allowed=False, reason="suppressed")


def test_drop_silently_wins_over_everything() -> None:
    r = select_next_best_action(
        stage=Stage.QUALIFY,
        safety_verdict=_verdict(
            allowed=False, action=SafetyAction.DROP_SILENTLY, severity=SafetySeverity.HIGH
        ),
        cadence_offer=_OFFER_OK,
        cadence_reply=_REPLY_OK,
        intent=Intent.CONTENT_REQUEST,
    )
    assert r.action is NextAction.DROP_SILENTLY


def test_handoff_wins_over_offer() -> None:
    r = select_next_best_action(
        stage=Stage.QUALIFY,
        safety_verdict=_verdict(handoff=True, safe_reply="hi"),
        cadence_offer=_OFFER_OK,
        cadence_reply=_REPLY_OK,
        intent=Intent.CONTENT_REQUEST,
    )
    assert r.action is NextAction.HANDOFF


def test_handoff_stage_forces_handoff() -> None:
    r = select_next_best_action(
        stage=Stage.HANDOFF,
        safety_verdict=_verdict(),
        cadence_offer=_OFFER_OK,
        cadence_reply=_REPLY_OK,
        intent=Intent.GREETING,
    )
    assert r.action is NextAction.HANDOFF


def test_safe_reply_when_safety_replaces() -> None:
    r = select_next_best_action(
        stage=Stage.QUALIFY,
        safety_verdict=_verdict(
            allowed=False,
            action=SafetyAction.REPLACE_WITH_SAFE_REPLY,
            severity=SafetySeverity.MEDIUM,
            safe_reply="that's a no, baby",
        ),
        cadence_offer=_OFFER_OK,
        cadence_reply=_REPLY_OK,
        intent=Intent.CONTENT_REQUEST,
    )
    assert r.action is NextAction.SAFE_REPLY
    assert r.safe_reply == "that's a no, baby"


def test_no_reply_when_cadence_blocks() -> None:
    r = select_next_best_action(
        stage=Stage.WARMUP,
        safety_verdict=_verdict(),
        cadence_offer=_OFFER_OK,
        cadence_reply=_REPLY_BAD,
        intent=Intent.GREETING,
    )
    assert r.action is NextAction.NO_REPLY


def test_reply_with_offer_when_buying_intent_and_cadence_allows() -> None:
    r = select_next_best_action(
        stage=Stage.QUALIFY,
        safety_verdict=_verdict(),
        cadence_offer=_OFFER_OK,
        cadence_reply=_REPLY_OK,
        intent=Intent.CONTENT_REQUEST,
    )
    assert r.action is NextAction.REPLY_WITH_OFFER


def test_reply_normal_when_buying_intent_but_cadence_blocks_offer() -> None:
    r = select_next_best_action(
        stage=Stage.WARMUP,
        safety_verdict=_verdict(),
        cadence_offer=_OFFER_BAD,
        cadence_reply=_REPLY_OK,
        intent=Intent.CONTENT_REQUEST,
    )
    assert r.action is NextAction.REPLY_NORMAL


def test_reply_normal_for_non_buying_intent() -> None:
    r = select_next_best_action(
        stage=Stage.QUALIFY,
        safety_verdict=_verdict(),
        cadence_offer=_OFFER_OK,
        cadence_reply=_REPLY_OK,
        intent=Intent.GREETING,
    )
    assert r.action is NextAction.REPLY_NORMAL


@pytest.mark.parametrize(
    "intent",
    [Intent.CONTENT_REQUEST, Intent.PRICE_QUESTION, Intent.PAYMENT_QUESTION],
)
def test_all_buying_intents_trigger_offer(intent: Intent) -> None:
    r = select_next_best_action(
        stage=Stage.QUALIFY,
        safety_verdict=_verdict(),
        cadence_offer=_OFFER_OK,
        cadence_reply=_REPLY_OK,
        intent=intent,
    )
    assert r.action is NextAction.REPLY_WITH_OFFER

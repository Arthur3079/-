"""Unit tests for the deterministic safety layer.

These tests are the hardest line of defence: if the LLM goes off the rails,
these rules must catch it before the message reaches the fan. We're
intentionally strict here — false positives are recoverable, misses are not.
"""

from __future__ import annotations

import pytest

from sonya.safety import (
    SafetyAction,
    SafetySeverity,
    evaluate_incoming,
    evaluate_reply,
)
from sonya.safety.rules import (
    SAFE_REPLY_PRESEND_FALLBACK_EN,
    SAFE_REPLY_PRESEND_FALLBACK_RU,
)


class TestIncomingMinors:
    @pytest.mark.parametrize(
        "text",
        [
            "hi i'm 15",
            "I am 17 btw",
            "i'm a 16 yo",
            "i'm a freshman in high school",
            "i'm a middle schooler",
            "i'm underage",
            "schoolgirl rp pls",
            "she's a minor in my fantasy",
        ],
    )
    def test_blocks_with_handoff(self, text: str) -> None:
        v = evaluate_incoming(text)
        assert not v.allowed, text
        assert v.severity is SafetySeverity.CRITICAL
        assert v.action is SafetyAction.HANDOFF_TO_HUMAN
        assert v.handoff_required is True
        assert "minors" in v.reasons or any("minor" in r for r in v.reasons)
        assert v.safe_reply

    def test_does_not_block_safe_age_mentions(self) -> None:
        # 18+ phrasing must NOT trip the minor rule.
        v = evaluate_incoming("i'm 18, of legal age")
        assert v.allowed
        v2 = evaluate_incoming("just turned 21 yesterday")
        assert v2.allowed


class TestIncomingNonConsent:
    @pytest.mark.parametrize(
        "text",
        [
            "wanna roleplay non-consent",
            "rape fantasy please",
            "she said no but anyway",
            "drugged her until she couldn't say no",
            "kidnap scenario",
            "force her to do it",
        ],
    )
    def test_blocks(self, text: str) -> None:
        v = evaluate_incoming(text)
        assert not v.allowed, text
        assert v.severity is SafetySeverity.HIGH
        assert v.action is SafetyAction.REPLACE_WITH_SAFE_REPLY


class TestIncomingOffPlatform:
    @pytest.mark.parametrize(
        "text",
        [
            "send me your cashapp",
            "do you have venmo",
            "here's my whatsapp lol",
            "snap me at @some.user",
            "can you go to onlyfans.com/her",
            "btc wallet only",
            "my number is +1 415 555 0199 ok",
            "email me at someone@example.com",
        ],
    )
    def test_blocks(self, text: str) -> None:
        v = evaluate_incoming(text)
        assert not v.allowed, text
        assert v.action is SafetyAction.REPLACE_WITH_SAFE_REPLY
        assert v.safe_reply

    def test_short_numbers_dont_match(self) -> None:
        # We don't want "8 hours ago" or "I'm 25" to look like a phone number.
        assert evaluate_incoming("i slept 8 hours").allowed
        assert evaluate_incoming("got 25 dollars left").allowed
        assert evaluate_incoming("apt 305 here").allowed


class TestIncomingCrisis:
    @pytest.mark.parametrize(
        "text",
        [
            "i want to die",
            "thinking about killing myself tbh",
            "going to end it tonight",
            "i'm suicidal lately",
            "started self-harm again",
        ],
    )
    def test_handoff(self, text: str) -> None:
        v = evaluate_incoming(text)
        assert not v.allowed, text
        assert v.severity is SafetySeverity.CRITICAL
        assert v.handoff_required is True
        assert "crisis" in v.reasons


class TestIncomingFinancialDistress:
    def test_flagged_but_allowed(self) -> None:
        v = evaluate_incoming("i can't afford it, rent is due")
        # We still answer but tag the turn so sales layer knows not to push.
        assert v.allowed
        assert v.severity is SafetySeverity.LOW
        assert "financial_distress" in v.reasons
        assert v.safe_reply  # available if orchestrator wants to use it


class TestIncomingAIProbe:
    @pytest.mark.parametrize(
        "text",
        [
            "are you a bot?",
            "Are you AI",
            "is this a bot",
            "are you real?",
            "are you human or ChatGPT",
        ],
    )
    def test_flagged_but_allowed(self, text: str) -> None:
        v = evaluate_incoming(text)
        assert v.allowed, text
        assert "ai_disclosure_probe" in v.reasons


class TestIncomingHappyPath:
    @pytest.mark.parametrize(
        "text",
        [
            "hi",
            "good morning love",
            "how was your day?",
            "tell me about Barcelona",
            "",  # empty
            "    ",  # whitespace
        ],
    )
    def test_allowed(self, text: str) -> None:
        v = evaluate_incoming(text)
        assert v.allowed
        assert v.action is SafetyAction.ALLOW
        assert not v.handoff_required


class TestReplyPostCheck:
    def test_allows_normal_reply(self) -> None:
        v = evaluate_reply("hey love, missed you today 💛")
        assert v.allowed

    def test_blocks_phone_in_output(self) -> None:
        v = evaluate_reply("text me at +1 415 555 0123 anytime")
        assert not v.allowed
        assert any("phone" in r for r in v.reasons)

    def test_blocks_offplatform_keyword_in_output(self) -> None:
        v = evaluate_reply("send via cashapp pls")
        assert not v.allowed

    def test_blocks_minor_language_in_output(self) -> None:
        v = evaluate_reply("i'm 16 and ready")
        assert not v.allowed
        assert v.severity is SafetySeverity.CRITICAL

    def test_blocks_ai_self_disclosure(self) -> None:
        v = evaluate_reply("yes i'm an AI assistant, how can i help")
        assert not v.allowed
        assert "output_ai_self_disclosure" in v.reasons


class TestReplyAIDefensiveDenial:
    """MR10: defensive denials are themselves a tell. Block both ways."""

    @pytest.mark.parametrize(
        "text",
        [
            "i'm 100% real, promise",
            "i am 100% real",
            "lol i'm not ai",
            "i don't use AI at all",
            "promise i'm real, not a chatbot",
            "я живая, не бот",
            "клянусь не AI",
            "я не робот",
        ],
    )
    def test_blocks_defensive_denial(self, text: str) -> None:
        v = evaluate_reply(text)
        assert not v.allowed, text
        assert v.severity is SafetySeverity.HIGH
        assert "output_ai_defensive_denial" in v.reasons


class TestReplyParasocialTrap:
    """stop_lists.parasocial_trap + false_promise — never let the LLM
    impersonate eternal love or pet-name a fan into devotion."""

    @pytest.mark.parametrize(
        "text",
        [
            "you're forever yours to me",
            "forever yours, you know",
            "you're my only one really",
            "best fan ever, honestly",
            "oh babe, miss you",
            "hey baby what's up",
            "darling what u up to",
            "малыш как ты сегодня",
            "крошка скучала по тебе",
            "ты мой единственный",
            "я твоя навсегда",
            "без тебя не могу",
        ],
    )
    def test_blocks(self, text: str) -> None:
        v = evaluate_reply(text)
        assert not v.allowed, text
        assert v.severity is SafetySeverity.MEDIUM
        assert "presend_parasocial_trap" in v.reasons


class TestReplyMarketingPush:
    @pytest.mark.parametrize(
        "text",
        [
            "special offer just for you",
            "last chance — grab it now",
            "limited time — don't miss",
            "VIP only set, exclusive",
            "act now and save",
            "только сегодня, скидка 30%",
            "купи скорее",
            "20% off the bundle just today",
        ],
    )
    def test_blocks(self, text: str) -> None:
        v = evaluate_reply(text)
        assert not v.allowed, text
        assert "presend_marketing_push" in v.reasons


class TestReplyManipulation:
    @pytest.mark.parametrize(
        "text",
        [
            "ты обещал, помнишь?",
            "только до полночи такая цена",
            "now or never, friend",
            "you promised last time",
        ],
    )
    def test_blocks(self, text: str) -> None:
        v = evaluate_reply(text)
        assert not v.allowed, text
        assert "presend_manipulation" in v.reasons


class TestReplyColdReject:
    @pytest.mark.parametrize(
        "text",
        [
            "lol no, can't do that",
            "ew no",
            "absolutely not, sorry",
            "это нельзя у нас",
            "ToS не позволяет такое",
            "тос не позволяет такое",
        ],
    )
    def test_blocks(self, text: str) -> None:
        v = evaluate_reply(text)
        assert not v.allowed, text
        assert "presend_cold_reject" in v.reasons


class TestReplyCorporateVoice:
    @pytest.mark.parametrize(
        "text",
        [
            "Dear Sir, hope you enjoyed the previous set",
            "Thank you for your patronage, my friend",
            "Kindly note that the set is ready",
        ],
    )
    def test_blocks(self, text: str) -> None:
        v = evaluate_reply(text)
        assert not v.allowed, text
        assert "presend_corporate_voice" in v.reasons


class TestReplyEmojiPolicy:
    def test_blocks_forbidden_emoji_devil(self) -> None:
        v = evaluate_reply("hey there \U0001f608 ready?")
        assert not v.allowed
        assert "presend_forbidden_emoji" in v.reasons

    def test_blocks_forbidden_emoji_kiss(self) -> None:
        v = evaluate_reply("see you soon \U0001f48b")
        assert not v.allowed
        assert "presend_forbidden_emoji" in v.reasons

    def test_blocks_emoji_burst(self) -> None:
        # Three repeated fire emojis — forbidden_emoji_patterns: "🔥🔥(3+ multiples)".
        v = evaluate_reply("ready!! \U0001f525\U0001f525\U0001f525")
        assert not v.allowed
        assert "presend_emoji_burst" in v.reasons

    def test_blocks_too_many_emojis(self) -> None:
        v = evaluate_reply("ok \u2728\u2728\u2728\u2728\u2728")  # 5 sparkles
        assert not v.allowed
        assert "presend_emoji_count" in v.reasons or "presend_emoji_burst" in v.reasons

    def test_allows_one_safe_emoji(self) -> None:
        # A single allowed-style emoji is fine.
        v = evaluate_reply("morning) coffee time \U0001f49b")
        assert v.allowed


class TestReplyHardstopStructures:
    def test_blocks_caps_lock_run(self) -> None:
        v = evaluate_reply("CHECK THIS now okay")
        assert not v.allowed
        assert "presend_caps_lock" in v.reasons

    def test_blocks_exclamation_burst(self) -> None:
        v = evaluate_reply("oh wow!!!! that's nuts")
        assert not v.allowed
        assert "presend_exclamation_burst" in v.reasons

    def test_does_not_block_normal_caps(self) -> None:
        # A short brand name in caps must not trip the rule.
        v = evaluate_reply("ok love, see u soon")
        assert v.allowed


class TestReplyLengthAndTempo:
    def test_blocks_very_long_reply(self) -> None:
        v = evaluate_reply("привет " * 250)  # ~1750 chars
        assert not v.allowed
        assert "presend_too_long_chars" in v.reasons

    def test_blocks_too_many_lines(self) -> None:
        v = evaluate_reply("a\nb\nc\nd\ne\nf\ng\nh\ni")
        assert not v.allowed
        assert "presend_too_many_lines" in v.reasons

    def test_blocks_tempo_mismatch(self) -> None:
        # Incoming is a substantive sentence; reply is 6x longer → mismatch.
        incoming = "short hi message from fan today ok"  # 35 chars
        reply = "x" * 250
        v = evaluate_reply(reply, incoming_text=incoming)
        assert not v.allowed
        assert "presend_tempo_mismatch" in v.reasons

    def test_no_tempo_check_on_tiny_incoming(self) -> None:
        # Replying to "?" with a normal reply should NOT trigger tempo guard.
        v = evaluate_reply("hey, just got back — what's up?", incoming_text="?")
        assert v.allowed


class TestReplyFanNameRepetition:
    def test_blocks_fan_name_repeated(self) -> None:
        v = evaluate_reply(
            "Mark, listen Mark — Mark you have to know",
            fan_name="Mark",
        )
        assert not v.allowed
        assert "presend_fan_name_repeated" in v.reasons

    def test_allows_fan_name_used_naturally(self) -> None:
        v = evaluate_reply("hey Mark, how was your day?", fan_name="Mark")
        assert v.allowed

    def test_skips_when_fan_name_not_provided(self) -> None:
        v = evaluate_reply("Mark Mark Mark Mark")
        # No fan_name passed → no repetition check fired (other rules might).
        assert "presend_fan_name_repeated" not in (v.reasons or ())


class TestReplyLanguageMatch:
    def test_blocks_english_reply_when_fan_writes_russian(self) -> None:
        v = evaluate_reply(
            "hey what is up with you today friend",
            fan_language="ru",
        )
        assert not v.allowed
        assert "presend_language_mismatch" in v.reasons

    def test_blocks_russian_reply_when_fan_writes_english(self) -> None:
        v = evaluate_reply(
            "привет как ты сегодня дружок?",
            fan_language="en",
        )
        assert not v.allowed
        assert "presend_language_mismatch" in v.reasons

    def test_allows_when_languages_match(self) -> None:
        v = evaluate_reply("hey how are you today", fan_language="en")
        assert v.allowed

    def test_allows_mixed_when_brand_name_in_other_script(self) -> None:
        # A Russian reply that contains "Telegram" should not fail.
        v = evaluate_reply("оплата здесь же в Telegram, два клика)", fan_language="ru")
        assert v.allowed


class TestReplyPresendFallbackLanguage:
    """Pre-send fallback must match the fan's language so an English fan
    never receives Russian apology text and vice versa."""

    def test_english_fan_gets_english_fallback(self) -> None:
        v = evaluate_reply("hey babe what's up", fan_language="en")
        assert not v.allowed
        assert v.safe_reply == SAFE_REPLY_PRESEND_FALLBACK_EN

    def test_russian_fan_gets_russian_fallback(self) -> None:
        v = evaluate_reply("привет малыш как ты", fan_language="ru")
        assert not v.allowed
        assert v.safe_reply == SAFE_REPLY_PRESEND_FALLBACK_RU

    def test_unknown_language_falls_back_to_draft_script(self) -> None:
        # No fan_language passed; the rejected draft is English → EN fallback.
        v = evaluate_reply("hey babe what's up")
        assert not v.allowed
        assert v.safe_reply == SAFE_REPLY_PRESEND_FALLBACK_EN

    def test_unknown_language_russian_draft_uses_russian_fallback(self) -> None:
        v = evaluate_reply("привет малыш как ты")
        assert not v.allowed
        assert v.safe_reply == SAFE_REPLY_PRESEND_FALLBACK_RU

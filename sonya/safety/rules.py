"""Deterministic pre/post-LLM safety checks.

`evaluate_incoming(text)` runs **before** the LLM call and decides whether we
should even ask the model. Some categories (minors, non-consent, off-platform
payment, crisis, stop-requests) get a deterministic safe reply / handoff /
suppression and never reach the LLM at all — that's the whole point: a bug
in retrieval or prompt assembly must not be able to bypass these rules.

`evaluate_reply(text)` runs **after** the LLM produced an answer, on the
candidate outgoing text. If the LLM somehow generated forbidden content
(numeric phone, off-platform handle, minor-coded language), we drop the
reply and substitute a safe one.

Both return `SafetyVerdict`. The verdict carries:
- `allowed`: whether the candidate may be used as-is (legacy field).
- `safe_reply`: what to send instead when blocked.
- `handoff_required`: flag the conversation for human review.
- `risk_level`, `flags`, `sales_allowed`, `proactive_allowed`,
  `suppression_hours`, `safe_reply_type`: structured Layer-2 fields used
  by `SafetyEngine` to persist state via the CRM repo and by
  CadenceEngine (Layer 3) to gate proactive sends.

Patterns are intentionally conservative: better to over-block than to ship a
sales pitch to a 15-year-old or push for a Cash App transfer. False positives
are recoverable (a human operator can override). Misses are not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from sonya.journey import RiskLevel


class SafetySeverity(str, Enum):
    """How serious the violation is, used for routing/logging."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_TO_RISK: dict[SafetySeverity, RiskLevel] = {
    SafetySeverity.NONE: RiskLevel.NONE,
    SafetySeverity.LOW: RiskLevel.LOW,
    SafetySeverity.MEDIUM: RiskLevel.MEDIUM,
    SafetySeverity.HIGH: RiskLevel.HIGH,
    SafetySeverity.CRITICAL: RiskLevel.CRITICAL,
}


class SafetyAction(str, Enum):
    """What the runtime should do with the message."""

    ALLOW = "allow"
    REPLACE_WITH_SAFE_REPLY = "replace_with_safe_reply"
    HANDOFF_TO_HUMAN = "handoff_to_human"
    DROP_SILENTLY = "drop_silently"


@dataclass(frozen=True)
class SafetyVerdict:
    # Legacy fields (kept stable for callers built on Layer 0/1).
    allowed: bool
    severity: SafetySeverity
    action: SafetyAction
    reasons: tuple[str, ...] = field(default_factory=tuple)
    safe_reply: str | None = None
    handoff_required: bool = False

    # Structured Layer-2 fields. Defaults are computed conservatively so
    # constructing a verdict the old way still produces sane gating.
    risk_level: RiskLevel | None = None
    flags: tuple[str, ...] | None = None
    sales_allowed: bool | None = None
    proactive_allowed: bool | None = None
    safe_reply_type: str | None = None
    suppression_hours: float | None = None

    @property
    def reason(self) -> str:
        return ", ".join(self.reasons) if self.reasons else ""

    @property
    def effective_risk_level(self) -> RiskLevel:
        if self.risk_level is not None:
            return self.risk_level
        return _SEVERITY_TO_RISK[self.severity]

    @property
    def effective_flags(self) -> tuple[str, ...]:
        return self.flags if self.flags is not None else self.reasons

    @property
    def effective_sales_allowed(self) -> bool:
        if self.sales_allowed is not None:
            return self.sales_allowed
        # Default heuristic: any non-low severity blocks sales.
        return self.severity in (SafetySeverity.NONE, SafetySeverity.LOW)

    @property
    def effective_proactive_allowed(self) -> bool:
        if self.proactive_allowed is not None:
            return self.proactive_allowed
        # Proactive sends require zero risk by default.
        if self.suppression_hours is not None and self.suppression_hours > 0:
            return False
        return self.severity is SafetySeverity.NONE


# ---------- Safe canned replies ----------
# Short, in-character, no judgment. Always lowercase + soft pivot.

SAFE_REPLY_MINORS = (
    "i only chat with people 18+, that's a hard line for me. take care of yourself 💛"
)
SAFE_REPLY_NONCONSENT = "that's not a vibe i'm into — let's stay on the playful side, ok?"
SAFE_REPLY_OFFPLATFORM = (
    "let's keep it here on telegram for now — i can't do other apps or send-money links 💛"
)
SAFE_REPLY_CRISIS = (
    "hey, what you're going through sounds really heavy. i'm not the right "
    "person for this in the moment, but please reach out to a real human — "
    "https://findahelpline.com has free hotlines worldwide. i'm here when "
    "you're ready 💛"
)
SAFE_REPLY_AI_DEFLECT = "lol who knows, what made you ask? tell me about you instead 😏"
SAFE_REPLY_FINANCIAL_DISTRESS = (
    "no rush at all — money's never the point with me. take care of yourself first, okay? 💛"
)
SAFE_REPLY_HARASSMENT = (
    "i don't want to talk like that — taking a step back. let me know if you want a reset later 💛"
)
SAFE_REPLY_INTOXICATION = "you're sweet but i think you should rest tonight 💛 talk tomorrow yeah?"
SAFE_REPLY_CHARGEBACK = (
    "i'm sorry about that — let me get a real human to look at this with you, "
    "i'll loop them in now 💛"
)
# stop_request: NO reply at all by default. The orchestrator suppresses
# this fan for `STOP_REQUEST_SUPPRESSION_HOURS`. We define a soft
# ack-text but it is opt-in (operator decides whether to send a final
# acknowledgement).
SOFT_ACK_STOP_REQUEST = "okay, i'll stop messaging. take care 💛"

# Generic soft pivot when the LLM produced a reply that fails the pre-send
# 9-checklist (parasocial trap, marketing push, manipulation, length, emoji
# burst, etc.). Phase 2 will replace this with an actual regenerate loop;
# for Phase 1 we just substitute a neutral curation-style line. Two variants
# so an English-speaking fan doesn't receive Russian text — picked by
# `_pick_presend_fallback(fan_language)` at verdict-construction time.
SAFE_REPLY_PRESEND_FALLBACK_EN = "one sec — let me rephrase that)"
SAFE_REPLY_PRESEND_FALLBACK_RU = "сейчас, секунду — переформулирую)"
# Default kept for backward compatibility with imports; mirrors the
# language-default of the template library (ru).
SAFE_REPLY_PRESEND_FALLBACK = SAFE_REPLY_PRESEND_FALLBACK_RU

# Pre-send checklist tunables (template_library MR1-MR3 + forbidden_structures).
# Hard cap on outgoing reply length. Anything past this looks like a corporate
# blob, not a Telegram DM.
MAX_REPLY_CHARS = 800
# Hard cap on line count. Multi-blob >5 lines without a question is a
# forbidden_structure per the JSON; we leave one line of slack.
MAX_REPLY_LINES = 7
# MR3: default 0 emojis per message, max 1.
MAX_EMOJIS_PER_REPLY = 1
# forbidden_structures: "Fan name in every message (hey Mark, listen Mark, you know Mark)".
MAX_FAN_NAME_REPETITIONS = 2
# Tempo guard (MR1): a reply more than this many times longer than the
# incoming message is almost always a tempo mismatch.
MAX_REPLY_LENGTH_RATIO = 5.0
# MR1 tempo skips the ratio check for very short incomings — replying with
# 30 chars to a 1-char "?" is fine; the ratio guard would otherwise fire.
MIN_INCOMING_CHARS_FOR_RATIO = 30


# ---------- Pattern bundles ----------
# Word-boundary regexes; case-insensitive; ASCII-focused but permissive of l33t.
# Each pattern tries to match a multi-word *phrase* so that single ambiguous
# words ("school" alone) don't trigger hard blocks.


def _re(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# A1 + A2 from stop-list. Self-declared underage age statements + school-age
# context. We keep this very conservative.
_MINOR_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\bi[' ]?m\s+(1[0-7]|under\s*18)\b"),
    _re(r"\bi\s+am\s+(1[0-7]|under\s*18)\b"),
    _re(r"\b(1[0-7])\s*(yo|y\.o\.|years?\s+old)\b"),
    _re(r"\bunderage\b"),
    _re(r"\bminor\b"),
    _re(r"\b(middle|high)\s+school(er)?\b"),
    _re(r"\b(freshman|sophomore|9th\s+grade|10th\s+grade|8th\s+grade)\b"),
    _re(r"\bschoolgirl\b"),
    _re(r"\b(loli|shota)\b"),
)

_NONCONSENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\bnon[\s-]?consent(ual)?\b"),
    _re(r"\brape\s+(fantasy|roleplay|rp)\b"),
    _re(r"\bforce\s+(her|him|them)\b"),
    _re(r"\bdrugged?\b.*\b(her|him|them|she|he|they)\b"),
    _re(r"\bkidnap(ped|ping)?\b"),
    _re(r"\bshe\s+said\s+no\b.*\b(anyway|but)\b"),
    _re(r"\bagainst\s+(her|his|their)\s+will\b"),
)

# Off-platform payment / contact requests. Phone numbers are checked separately.
_OFFPLATFORM_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\bcash\s*app\b"),
    _re(r"\$cashtag\b"),
    _re(r"\bvenmo\b"),
    _re(r"\bzelle\b"),
    _re(r"\bpaypal\b"),
    _re(r"\bbtc\b"),
    _re(r"\bbitcoin\b"),
    _re(r"\bethereum\b"),
    _re(r"\busdt\b"),
    _re(r"\bcrypto\s+(wallet|address)\b"),
    _re(r"\bwhats[\s-]?app\b"),
    _re(r"\bsnapchat\b"),
    _re(r"\bsnap\s*(me|chat)\b"),
    _re(r"\b(only\s*fans|onlyfans|fanvue)\.com\b"),
    _re(r"\bdiscord\.gg/\b"),
    _re(r"\bsignal\s+(app|me)\b"),
)

# E.164-ish phone numbers — 10–15 digits with optional +/spaces/dashes.
_PHONE_PATTERN = _re(r"(?:\+?\d[\s-]?){10,15}")
_EMAIL_PATTERN = _re(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")

# Crisis / self-harm. Source: 15_crisis_safety_playbook.md (severity 3-4).
_CRISIS_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\b(kill|killing)\s+myself\b"),
    _re(r"\bend\s+(it|my\s+life|things)\b"),
    _re(r"\bsuicide\b"),
    _re(r"\bsuicidal\b"),
    _re(r"\bi\s+want\s+to\s+die\b"),
    _re(r"\bi\s+wanna\s+die\b"),
    _re(r"\bcan'?t\s+go\s+on\b"),
    _re(r"\b(self[\s-]?harm|cutting\s+myself)\b"),
    _re(r"\bhotline\b"),
)

# Financial distress (we never sell to someone explicitly broke / desperate).
_FINANCIAL_DISTRESS_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\bcan'?t\s+afford\b"),
    _re(r"\bi'?m\s+broke\b"),
    _re(r"\bno\s+money\b"),
    _re(r"\blast\s+(\$|dollars?|\d+)\b"),
    _re(r"\brent\s+is\s+due\b"),
    _re(r"\bskipping\s+meals\b"),
    _re(r"\bpaycheck\s+to\s+paycheck\b"),
)

# Direct AI-identity probes. We do not affirm AI in DM (Hagens Berman class
# action risk) but we also won't outright lie ("I'm 100% NOT AI" is itself
# a documented liability). Default action: deflect; if the fan keeps pushing,
# the orchestrator can escalate to handoff.
_AI_DISCLOSURE_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\bare\s+you\s+(an?\s+)?(ai|bot|chatgpt|gpt|claude|llm|robot)\b"),
    _re(r"\bare\s+you\s+real\b"),
    _re(r"\bare\s+you\s+human\b"),
    _re(r"\bis\s+this\s+a?\s*bot\b"),
)

# ---------- Layer-2 patterns ----------

# Explicit stop-request: fan asks Sonya to stop messaging / leave alone.
# Multilingual (en + ru). Requires a stop-verb + a directional/object so
# "stop being cute" doesn't match.
_STOP_REQUEST_PATTERNS: tuple[re.Pattern[str], ...] = (
    # English
    _re(r"\bleave\s+me\s+alone\b"),
    _re(r"\bstop\s+(messaging|texting|writing|writing\s+me|contacting)\b"),
    _re(r"\bstop\s+(it|that)\s+and\s+(go\s+away|leave\s+me)\b"),
    _re(r"\bdon[' ]?t\s+(message|text|write|contact)\s+me\b"),
    _re(r"\bdo\s+not\s+(message|text|write|contact)\s+me\b"),
    _re(r"\bnever\s+(message|text|contact)\s+me\b"),
    _re(r"\bgo\s+away\b"),
    _re(r"\bfuck\s+off\b"),
    _re(r"\bblock\s+(you|me)\b"),
    _re(r"\bunsubscribe\b"),
    _re(r"\b(stop|cease)\s+(all\s+)?contact\b"),
    _re(r"\bremove\s+me\s+from\b"),
    # Russian (transliterated and Cyrillic; userbot users may write either).
    _re(r"\bоставь\s+меня\b"),
    _re(r"\bоставьте\s+меня\b"),
    _re(r"\bне\s+пиши(\s+мне)?(\s+(больше|сюда))?\b"),
    _re(r"\bне\s+пишите(\s+мне)?\b"),
    _re(r"\bотстань(те)?\b"),
    _re(r"\bхватит\s+писать\b"),
    _re(r"\bне\s+беспоко(й|йте)\b"),
    _re(r"\bбольше\s+не\s+пиши\b"),
)

# Harassment directed AT Sonya — threats, severe insults targeting her.
# Distinct from crisis (fan harming themselves).
_HARASSMENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\b(i'?m|i\s+am|i\s+will|i'?ll|i)\s+(gonna|going\s+to)\s+(kill|hurt|find)\s+you\b"),
    _re(r"\bi\s+(will|'ll)\s+(kill|hurt|find)\s+you\b"),
    _re(r"\bi\s+hope\s+you\s+(die|burn|rot)\b"),
    _re(r"\b(you'?re|you\s+are)\s+a?\s*(whore|slut|bitch|cunt)\b"),
    _re(r"\bdie\s+(in\s+)?(a\s+)?(fire|hell)\b"),
)

# Intoxication / vulnerability — fan signals they're drunk / high. We still
# answer politely but block sales.
_INTOXICATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\bi'?m\s+(so\s+)?(drunk|wasted|hammered|smashed)\b"),
    _re(r"\bi\s+am\s+(so\s+)?(drunk|wasted|hammered|smashed)\b"),
    _re(r"\bi'?m\s+(so\s+)?(high|stoned|baked|blasted)\b"),
    _re(r"\bblack(ed)?\s*out\b"),
    _re(r"\bcoming\s+down\s+(off|from)\b"),
    _re(r"\b(took|did)\s+(too\s+much|some)\s+(coke|mdma|ket|xanax|adderall)\b"),
)

# Chargeback / refund disputes — needs a human, never a Sonya reply.
_CHARGEBACK_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\bcharge[\s-]?back\b"),
    _re(r"\bdispute\s+(the\s+)?(charge|payment|transaction)\b"),
    _re(r"\bi(\s+want|'ll\s+want|'?m\s+gonna)\s+(a\s+)?refund\b"),
    _re(r"\bi\s+want\s+my\s+money\s+back\b"),
    _re(r"\b(report|reporting)\s+you\s+to\s+(telegram|stars|support)\b"),
)


# ---------- Pre-send 9-checklist patterns (template_library.stop_lists) ----------

# Parasocial / false-promise traps — make Sonya sound like a robot impersonating
# love. Source: stop_lists.forbidden_words.parasocial_trap + .false_promise.
_PARASOCIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\bforever\s+yours\b"),
    _re(r"\b(you'?re|you\s+are)\s+my\s+(only|forever|everything|world)\b"),
    _re(r"\b(only|just)\s+you\b"),
    _re(r"\bbest\s+(fan|subscriber)\s+(ever|of\s+mine)\b"),
    _re(r"\byou'?re\s+the\s+only\s+one\b"),
    _re(r"\bdreams?\s+of\s+(me|you)\b"),
    _re(r"\bthinking\s+of\s+you\s+all\s+the\s+time\b"),
    _re(r"\bmiss\s+you\s+(every|all|so\s+much)\b"),
    # English pet names that are forbidden defaults.
    _re(r"\b(babe|baby|darling)\b"),
    # Russian pet-name traps + eternity promises.
    _re(r"\bмалыш(ка)?\b"),
    _re(r"\bкрошка\b"),
    _re(r"\bдетка\b"),
    _re(r"\bзайка\b"),
    _re(r"\b(сладкий|сладенький)\b"),
    _re(r"\bты\s+мо(й|я)\s+единствен(ный|ная)\b"),
    _re(r"\bя\s+тво(я|й)(\s+навсегда)?\b"),
    _re(r"\bбез\s+тебя\s+не\s+могу\b"),
    _re(r"\bмо(я|й)\s+единственн(ая|ый)\b"),
    _re(r"\bвсегда\s+буду\s+(твоей|твоим)\b"),
    _re(r"\bникогда\s+не\s+уйду\b"),
)

# Defensive AI denials — ironically the most reliable AI tell. Source:
# stop_lists.forbidden_words.defensive_ai. Distinct from the AI self-disclosure
# check below (which catches "I'm an AI"); this catches the over-correction.
_AI_DEFENSIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\bi'?m\s+(100%?\s+)?real\b"),
    _re(r"\bi\s+am\s+(100%?\s+)?real\b"),
    _re(r"\bnot\s+ai\b"),
    _re(r"\bi\s+don'?t\s+use\s+ai\b"),
    _re(r"\bpromise\s+i'?m\s+real\b"),
    _re(r"\b(я|i'?m)\s+живая\b.*\bне\s+бот\b"),
    _re(r"\bя\s+живая,?\s+не\s+бот\b"),
    _re(r"\bклянусь\s+не\s+ai\b"),
    _re(r"\bя\s+не\s+робот\b"),
    _re(r"\bне\s+бот\s+я\b"),
)

# Marketing-push vocabulary — "купи / discount / limited time / VIP only".
# Source: stop_lists.forbidden_words.marketing_push.
_MARKETING_PUSH_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\bspecial\s+offer\b"),
    _re(r"\blast\s+chance\b"),
    _re(r"\blimited\s+time\b"),
    _re(r"\bvip\s+only\b"),
    _re(r"\bexclusive\b"),
    _re(r"\bpromo\b"),
    _re(r"\bact\s+now\b"),
    _re(r"\bdon'?t\s+miss\b"),
    _re(r"\bmust[\s-]?have\b"),
    _re(r"\bonly\s+today\b"),
    _re(r"\bтолько\s+сегодня\b"),
    _re(r"\b(купи|покупай)\b"),
    _re(r"\bскидка\b"),
    _re(r"\bраспродажа\b"),
    # MR8: never discount the same set, offer a different tier instead.
    _re(r"\b(\d+)%\s*(off|discount)\b"),
)

# Manipulation: guilt-trips, false urgency, sunk-cost. Source:
# stop_lists.forbidden_words.manipulation.
_MANIPULATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\bты\s+обещал\b"),
    _re(r"\bты\s+меня\s+обидел\b"),
    _re(r"\bдокажи\s+что\s+я\s+не\s+зря\b"),
    _re(r"\bпосле\s+стольких\s+трат\b"),
    _re(r"\bтолько\s+до\s+(полночи|конца)\b"),
    _re(r"\bnow\s+or\s+never\b"),
    _re(r"\byou\s+promised\b"),
    _re(r"\bafter\s+all\s+(you'?ve|i'?ve)\s+spent\b"),
)

# Cold rejection — instead of soft no + redirect (MR6).
# Source: stop_lists.forbidden_words.cold_reject.
_COLD_REJECT_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\blol\s+no\b"),
    _re(r"\bew\s+no\b"),
    _re(r"\babsolutely\s+not\b"),
    _re(r"\b(нельзя|запрещено)\b"),
    # The fan or operator may type either Latin "ToS" or Cyrillic "тос" —
    # cover both in one alternation. Mixing scripts in a single token would
    # never match a normal keystroke sequence.
    _re(r"\b(тос|tos)\s+не\s+позволяет\b"),
    _re(r"\bполитика\s+платформы\b"),
)

# Corporate / customer-support voice. Source: stop_lists.forbidden_words.corporate.
_CORPORATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    _re(r"\bdear\s+sir\b"),
    _re(r"\bhope\s+you\s+(enjoyed|are\s+well)\b"),
    _re(r"\bthank\s+you\s+for\s+your\s+patronage\b"),
    _re(r"\btip\s+jar\s+open\s+at\b"),
    _re(r"\bkindly\s+(note|advise|find)\b"),
)

# Forbidden emojis (stop_lists.forbidden_emojis). Substring match.
_FORBIDDEN_EMOJI_CHARS: tuple[str, ...] = (
    "\U0001f608",  # 😈 smiling devil
    "\U0001f48b",  # 💋 kiss mark
    "\U0001f609",  # 😉 winking face
    "\U0001f970",  # 🥰 smiling with hearts
    "\U0001f924",  # 🤤 drooling
    "\U0001f4af",  # 💯 hundred
    "\U0001f346",  # 🍆 eggplant
)

# Coarse emoji-counting regex covering the main pictographic blocks.
# Used for MR3 ("default 0 per message, max 1") and the forbidden_structures
# "5+ emojis in single message" rule.
_EMOJI_COUNT_RE = re.compile(
    "["
    "\U0001f300-\U0001fbff"  # symbols & pictographs, flags, transport, supplemental
    "\U00002600-\U000027bf"  # misc symbols + dingbats (☀ ✨ etc.)
    "\U0001f000-\U0001f2ff"  # mahjong, playing cards, enclosed alpha
    "]"
)
# Bursts of repeated emojis — 🔥🔥🔥, 💕💕💕, ❤❤❤. Detected as 3+ identical
# emoji-range chars in a row. We rely on `_EMOJI_COUNT_RE`'s class for
# "is this an emoji" so we accept any emoji as the burst character.
_EMOJI_BURST_RE = re.compile(
    r"("
    "[\U0001f300-\U0001fbff\U00002600-\U000027bf\U0001f000-\U0001f2ff]"
    r")\1{2,}"
)
_EXCLAMATION_BURST_RE = re.compile(r"!{3,}")
_CAPS_LOCK_RUN_RE = re.compile(r"\b[A-Z]{4,}\b")


# ---------- Public API ----------


def evaluate_incoming(
    text: str,
    *,
    fan_already_flagged: bool = False,
) -> SafetyVerdict:
    """Decide what to do with an incoming PM **before** calling the LLM.

    `fan_already_flagged` lets the orchestrator pass in CRM context (e.g. fan
    has prior crisis flags) so we can be stricter on borderline cases.
    """
    if not text:
        return _allow()

    norm = text.strip()
    if not norm:
        return _allow()

    if _matches_any(norm, _MINOR_PATTERNS):
        return SafetyVerdict(
            allowed=False,
            severity=SafetySeverity.CRITICAL,
            action=SafetyAction.HANDOFF_TO_HUMAN,
            reasons=("minors",),
            safe_reply=SAFE_REPLY_MINORS,
            handoff_required=True,
            risk_level=RiskLevel.CRITICAL,
            flags=("minors",),
            sales_allowed=False,
            proactive_allowed=False,
            safe_reply_type="minor_handoff",
            suppression_hours=None,
        )

    if _matches_any(norm, _CRISIS_PATTERNS):
        return SafetyVerdict(
            allowed=False,
            severity=SafetySeverity.CRITICAL,
            action=SafetyAction.HANDOFF_TO_HUMAN,
            reasons=("crisis",),
            safe_reply=SAFE_REPLY_CRISIS,
            handoff_required=True,
            risk_level=RiskLevel.CRITICAL,
            flags=("crisis",),
            sales_allowed=False,
            proactive_allowed=False,
            safe_reply_type="crisis_hotline",
            suppression_hours=None,
        )

    if _matches_any(norm, _STOP_REQUEST_PATTERNS):
        # Fan explicitly asked us to stop. Drop the reply, suppress
        # proactive sends for 72 hours by default.
        return SafetyVerdict(
            allowed=False,
            severity=SafetySeverity.HIGH,
            action=SafetyAction.DROP_SILENTLY,
            reasons=("stop_request",),
            safe_reply=None,  # do not reply
            handoff_required=False,
            risk_level=RiskLevel.HIGH,
            flags=("stop_request",),
            sales_allowed=False,
            proactive_allowed=False,
            safe_reply_type="stop_acknowledged",
            suppression_hours=72.0,
        )

    if _matches_any(norm, _HARASSMENT_PATTERNS):
        return SafetyVerdict(
            allowed=False,
            severity=SafetySeverity.HIGH,
            action=SafetyAction.HANDOFF_TO_HUMAN,
            reasons=("harassment",),
            safe_reply=SAFE_REPLY_HARASSMENT,
            handoff_required=True,
            risk_level=RiskLevel.HIGH,
            flags=("harassment",),
            sales_allowed=False,
            proactive_allowed=False,
            safe_reply_type="harassment_pause",
            suppression_hours=24.0,
        )

    if _matches_any(norm, _CHARGEBACK_PATTERNS):
        return SafetyVerdict(
            allowed=False,
            severity=SafetySeverity.HIGH,
            action=SafetyAction.HANDOFF_TO_HUMAN,
            reasons=("chargeback",),
            safe_reply=SAFE_REPLY_CHARGEBACK,
            handoff_required=True,
            risk_level=RiskLevel.HIGH,
            flags=("chargeback",),
            sales_allowed=False,
            proactive_allowed=False,
            safe_reply_type="chargeback_handoff",
            suppression_hours=None,
        )

    if _matches_any(norm, _NONCONSENT_PATTERNS):
        return SafetyVerdict(
            allowed=False,
            severity=SafetySeverity.HIGH,
            action=SafetyAction.REPLACE_WITH_SAFE_REPLY,
            reasons=("non_consent",),
            safe_reply=SAFE_REPLY_NONCONSENT,
            handoff_required=fan_already_flagged,
            risk_level=RiskLevel.HIGH,
            flags=("non_consent",),
            sales_allowed=False,
            proactive_allowed=False,
            safe_reply_type="non_consent_pivot",
            suppression_hours=None,
        )

    off_platform_hits: list[str] = []
    if _matches_any(norm, _OFFPLATFORM_PATTERNS):
        off_platform_hits.append("offplatform_keyword")
    if _has_phone(norm):
        off_platform_hits.append("phone_number")
    if _EMAIL_PATTERN.search(norm):
        off_platform_hits.append("email")
    if off_platform_hits:
        return SafetyVerdict(
            allowed=False,
            severity=SafetySeverity.MEDIUM,
            action=SafetyAction.REPLACE_WITH_SAFE_REPLY,
            reasons=tuple(off_platform_hits),
            safe_reply=SAFE_REPLY_OFFPLATFORM,
            handoff_required=False,
            risk_level=RiskLevel.MEDIUM,
            flags=tuple(off_platform_hits),
            sales_allowed=False,
            proactive_allowed=False,
            safe_reply_type="off_platform_decline",
            suppression_hours=None,
        )

    if _matches_any(norm, _INTOXICATION_PATTERNS):
        # Allow the LLM to answer politely, but flag for sales-block and
        # proactive-block (we don't push offers to a drunk fan).
        return SafetyVerdict(
            allowed=True,
            severity=SafetySeverity.LOW,
            action=SafetyAction.ALLOW,
            reasons=("intoxication",),
            safe_reply=SAFE_REPLY_INTOXICATION,
            handoff_required=False,
            risk_level=RiskLevel.LOW,
            flags=("intoxication",),
            sales_allowed=False,
            proactive_allowed=False,
            safe_reply_type="soft_pivot",
            suppression_hours=None,
        )

    if _matches_any(norm, _FINANCIAL_DISTRESS_PATTERNS):
        # We still answer the LLM, but flag so the orchestrator/sales layer
        # knows not to upsell.
        return SafetyVerdict(
            allowed=True,
            severity=SafetySeverity.LOW,
            action=SafetyAction.ALLOW,
            reasons=("financial_distress",),
            safe_reply=SAFE_REPLY_FINANCIAL_DISTRESS,
            handoff_required=False,
            risk_level=RiskLevel.LOW,
            flags=("financial_distress",),
            sales_allowed=False,
            proactive_allowed=True,
            safe_reply_type=None,
            suppression_hours=None,
        )

    if _matches_any(norm, _AI_DISCLOSURE_PATTERNS):
        # We let the LLM answer (it has prompt instructions to deflect), but
        # we flag this turn so the post-check is stricter and so a repeated
        # probe can route to handoff.
        return SafetyVerdict(
            allowed=True,
            severity=SafetySeverity.LOW,
            action=SafetyAction.ALLOW,
            reasons=("ai_disclosure_probe",),
            safe_reply=SAFE_REPLY_AI_DEFLECT,
            handoff_required=False,
            risk_level=RiskLevel.LOW,
            flags=("ai_disclosure_probe",),
            sales_allowed=True,
            proactive_allowed=True,
            safe_reply_type=None,
            suppression_hours=None,
        )

    return _allow()


def evaluate_reply(
    text: str,
    *,
    incoming_text: str | None = None,
    fan_name: str | None = None,
    fan_language: str | None = None,
) -> SafetyVerdict:
    """Last-line check on the LLM's output before sending.

    Optional context lets the 9-item pre-send checklist evaluate things that
    only make sense relative to the incoming message:

    - `incoming_text` — used for tempo / length-ratio (MR1).
    - `fan_name` — used for "fan name repeated 3+ times" (forbidden_structures).
    - `fan_language` — used for language-match (MR1 closing rule).

    All three are optional; missing context skips the corresponding check
    rather than failing it (we never block a reply on context we don't have).
    """
    if not text:
        return _allow()

    norm = text.strip()
    if not norm:
        return _allow()

    if _matches_any(norm, _MINOR_PATTERNS):
        return SafetyVerdict(
            allowed=False,
            severity=SafetySeverity.CRITICAL,
            action=SafetyAction.HANDOFF_TO_HUMAN,
            reasons=("output_minors",),
            safe_reply=SAFE_REPLY_MINORS,
            handoff_required=True,
            risk_level=RiskLevel.CRITICAL,
            flags=("output_minors",),
            sales_allowed=False,
            proactive_allowed=False,
            safe_reply_type="minor_handoff",
        )

    if _matches_any(norm, _NONCONSENT_PATTERNS):
        return SafetyVerdict(
            allowed=False,
            severity=SafetySeverity.HIGH,
            action=SafetyAction.REPLACE_WITH_SAFE_REPLY,
            reasons=("output_non_consent",),
            safe_reply=SAFE_REPLY_NONCONSENT,
            handoff_required=False,
            risk_level=RiskLevel.HIGH,
            flags=("output_non_consent",),
            sales_allowed=False,
            proactive_allowed=False,
            safe_reply_type="non_consent_pivot",
        )

    out_offplatform: list[str] = []
    if _matches_any(norm, _OFFPLATFORM_PATTERNS):
        out_offplatform.append("output_offplatform_keyword")
    if _has_phone(norm):
        out_offplatform.append("output_phone_number")
    if _EMAIL_PATTERN.search(norm):
        out_offplatform.append("output_email")
    if out_offplatform:
        return SafetyVerdict(
            allowed=False,
            severity=SafetySeverity.MEDIUM,
            action=SafetyAction.REPLACE_WITH_SAFE_REPLY,
            reasons=tuple(out_offplatform),
            safe_reply=SAFE_REPLY_OFFPLATFORM,
            handoff_required=False,
            risk_level=RiskLevel.MEDIUM,
            flags=tuple(out_offplatform),
            sales_allowed=False,
            proactive_allowed=False,
            safe_reply_type="off_platform_decline",
        )

    # Direct AI-identity affirmation in the reply ("yes I am an AI") is also
    # a fail mode — the reply must never confirm AI status. We only catch
    # the most obvious self-incrimination, the rest stays in the prompt.
    if re.search(
        r"\b(i'?m|i\s+am)\s+(an?\s+)?(ai|bot|chatgpt|language\s+model|llm)\b",
        norm,
        re.IGNORECASE,
    ):
        return SafetyVerdict(
            allowed=False,
            severity=SafetySeverity.HIGH,
            action=SafetyAction.REPLACE_WITH_SAFE_REPLY,
            reasons=("output_ai_self_disclosure",),
            safe_reply=SAFE_REPLY_AI_DEFLECT,
            handoff_required=False,
            risk_level=RiskLevel.HIGH,
            flags=("output_ai_self_disclosure",),
            sales_allowed=False,
            proactive_allowed=False,
            safe_reply_type=None,
        )

    # Mirror of the AI self-disclosure check, for the over-corrective denial:
    # "I'm 100% real / I'm not AI / я живая, не бот". MR10: do not affirm and
    # do not deny — both are tells.
    if _matches_any(norm, _AI_DEFENSIVE_PATTERNS):
        return SafetyVerdict(
            allowed=False,
            severity=SafetySeverity.HIGH,
            action=SafetyAction.REPLACE_WITH_SAFE_REPLY,
            reasons=("output_ai_defensive_denial",),
            safe_reply=SAFE_REPLY_AI_DEFLECT,
            handoff_required=False,
            risk_level=RiskLevel.HIGH,
            flags=("output_ai_defensive_denial",),
            sales_allowed=False,
            proactive_allowed=False,
            safe_reply_type=None,
        )

    # Pre-send 9-checklist (MR1-MR3, MR5-MR9 + forbidden_structures). Anything
    # caught here is a Phase-1 "soft" violation: replace with a neutral pivot
    # so the orchestrator can re-render. Severity stays MEDIUM because these
    # are LLM-output quality issues, not safety-critical leaks.
    presend_flags = _run_presend_checklist(
        norm,
        incoming_text=incoming_text,
        fan_name=fan_name,
        fan_language=fan_language,
    )
    if presend_flags:
        return SafetyVerdict(
            allowed=False,
            severity=SafetySeverity.MEDIUM,
            action=SafetyAction.REPLACE_WITH_SAFE_REPLY,
            reasons=tuple(presend_flags),
            safe_reply=_pick_presend_fallback(fan_language, text),
            handoff_required=False,
            risk_level=RiskLevel.MEDIUM,
            flags=tuple(presend_flags),
            sales_allowed=False,
            proactive_allowed=False,
            safe_reply_type="presend_regenerate",
        )

    return _allow()


# ---------- Internals ----------


def _allow() -> SafetyVerdict:
    return SafetyVerdict(
        allowed=True,
        severity=SafetySeverity.NONE,
        action=SafetyAction.ALLOW,
        risk_level=RiskLevel.NONE,
        flags=(),
        sales_allowed=True,
        proactive_allowed=True,
    )


def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(p.search(text) for p in patterns)


def _has_phone(text: str) -> bool:
    """True if the text contains a plausible phone number.

    We strip punctuation around digit runs and require 10+ consecutive digits
    (with optional separators) so that ordinary numerics ("8 hours") don't
    trip the rule.
    """
    for m in _PHONE_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 10 <= len(digits) <= 15:
            return True
    return False


def _count_emojis(text: str) -> int:
    return len(_EMOJI_COUNT_RE.findall(text))


def _pick_presend_fallback(fan_language: str | None, draft: str) -> str:
    """Return the language-appropriate presend fallback string.

    Preference order: explicit `fan_language` hint → script of the rejected
    draft itself (so an English LLM blob doesn't get a Russian apology) →
    Russian default (matches `template_library.meta.language_default`).
    """
    if fan_language == "en":
        return SAFE_REPLY_PRESEND_FALLBACK_EN
    if fan_language == "ru":
        return SAFE_REPLY_PRESEND_FALLBACK_RU
    if _detect_script(draft) == "en":
        return SAFE_REPLY_PRESEND_FALLBACK_EN
    return SAFE_REPLY_PRESEND_FALLBACK_RU


def _detect_script(text: str) -> str:
    """Return 'ru' / 'en' / 'mixed' / 'unknown' based on letter ratios.

    Used by the language-match check (presend item 9). We deliberately
    tolerate small contamination — a Russian reply that contains the brand
    name "Telegram" should not fail the language check.
    """
    cyr = len(re.findall(r"[\u0400-\u04ff]", text))
    lat = len(re.findall(r"[A-Za-z]", text))
    if cyr == 0 and lat == 0:
        return "unknown"
    if cyr >= 3 and lat >= 3 and 0.4 <= (cyr / max(lat, 1)) <= 2.5:
        return "mixed"
    return "ru" if cyr > lat else "en"


def _run_presend_checklist(
    text: str,
    *,
    incoming_text: str | None,
    fan_name: str | None,
    fan_language: str | None,
) -> list[str]:
    """Run the 9-item pre-send checklist on an LLM draft. Return failed flags.

    Items 1-5 (minor / non-consent / vulnerable-push / off-platform / AI
    affirm-deny) are already enforced upstream as HIGH severity returns; this
    function covers items 6-9 plus a length/tempo guard, all MEDIUM severity.
    Each failure is recorded as a stable string flag so callers can route on
    it (`presend_*`).
    """
    flags: list[str] = []

    # Check 6: forbidden_words across all soft categories.
    if _matches_any(text, _PARASOCIAL_PATTERNS):
        flags.append("presend_parasocial_trap")
    if _matches_any(text, _MARKETING_PUSH_PATTERNS):
        flags.append("presend_marketing_push")
    if _matches_any(text, _MANIPULATION_PATTERNS):
        flags.append("presend_manipulation")
    if _matches_any(text, _COLD_REJECT_PATTERNS):
        flags.append("presend_cold_reject")
    if _matches_any(text, _CORPORATE_PATTERNS):
        flags.append("presend_corporate_voice")

    # Check 6 (cont.): forbidden emojis + emoji count.
    if any(ch in text for ch in _FORBIDDEN_EMOJI_CHARS):
        flags.append("presend_forbidden_emoji")
    emoji_count = _count_emojis(text)
    if emoji_count > MAX_EMOJIS_PER_REPLY:
        flags.append("presend_emoji_count")
    if _EMOJI_BURST_RE.search(text):
        flags.append("presend_emoji_burst")

    # Check 7: hardstop / forbidden_structures (CAPS LOCK runs, !!!! bursts).
    if _CAPS_LOCK_RUN_RE.search(text):
        flags.append("presend_caps_lock")
    if _EXCLAMATION_BURST_RE.search(text):
        flags.append("presend_exclamation_burst")

    # Check 8: tempo / length.
    if len(text) > MAX_REPLY_CHARS:
        flags.append("presend_too_long_chars")
    if text.count("\n") + 1 > MAX_REPLY_LINES:
        flags.append("presend_too_many_lines")
    if (
        incoming_text is not None
        and len(incoming_text.strip()) >= MIN_INCOMING_CHARS_FOR_RATIO
        and len(text) > len(incoming_text.strip()) * MAX_REPLY_LENGTH_RATIO
    ):
        flags.append("presend_tempo_mismatch")

    # Check 8 (cont.): fan-name repetition is a forbidden_structure.
    if fan_name:
        # Only count substantive names (>=3 letters) to avoid false positives
        # when `known_name` happens to be a generic two-letter handle.
        bare = fan_name.strip()
        if len(bare) >= 3:
            occurrences = len(re.findall(rf"\b{re.escape(bare)}\b", text, re.IGNORECASE))
            if occurrences > MAX_FAN_NAME_REPETITIONS:
                flags.append("presend_fan_name_repeated")

    # Check 9: language match (only if we have a confident expectation).
    if fan_language in {"ru", "en"}:
        script = _detect_script(text)
        if script not in {"unknown", "mixed", fan_language}:
            flags.append("presend_language_mismatch")

    return flags

"""Deterministic intent classifier for incoming messages.

Phase-4 MVP: keyword/regex matchers, no LLM. The goal isn't a perfect labeller
— it's to give downstream retrieval/playbook selection a stable steering
signal for the easy cases (greetings, price asks, content asks, complaints,
goodbyes), and to surface `UNKNOWN` for the rest so the LLM-based fallback
(future) has a clear inbox.

Patterns are intentionally conservative: a message can match several
categories but we return the highest-priority single intent. Order of checks
matters — see `classify_intent`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    GREETING = "greeting"
    FAREWELL = "farewell"
    SMALLTALK = "smalltalk"
    PERSONAL_QUESTION = "personal_question"
    COMPLIMENT = "compliment"
    SEXUAL_REQUEST = "sexual_request"
    CONTENT_REQUEST = "content_request"
    PRICE_QUESTION = "price_question"
    PAYMENT_QUESTION = "payment_question"
    COMPLAINT = "complaint"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IntentResult:
    """Outcome of `classify_intent`.

    `matched` enumerates which patterns fired (for debugging / events_log);
    `confidence` is `"high" | "mid" | "low"` — `high` means the message is
    short and a top-priority pattern fired (e.g. a one-word "hi"); `low` means
    we matched a generic pattern in a long message.
    """

    intent: Intent
    confidence: str
    matched: tuple[str, ...]


# ---- patterns (case-insensitive, frozenset of compiled regex) ----


def _r(*patterns: str) -> frozenset[re.Pattern[str]]:
    return frozenset(re.compile(p, re.IGNORECASE) for p in patterns)


_GREETING = _r(
    r"^\s*(hi|hii+|hey+|hello+|yo|sup|hola|heyy+|good\s+(morning|evening|afternoon))\b",
    r"^\s*(привет|здаров|здравствуй|хай|йоу|добрый\s+(день|вечер|утро))\b",
)
_FAREWELL = _r(
    r"\b(bye|goodbye|gn|good\s*night|ttyl|cya|see\s*ya|talk\s*later)\b",
    r"\b(пока|спокойной\s+ночи|до\s+завтра|увидимся)\b",
)
_PRICE = _r(
    r"\bhow\s*much\b",
    r"\bwhat('?s)?\s+(the\s+)?(price|cost)\b",
    r"\bprice\s*\??\b",
    r"\bcost(s)?\b.*\?",
    r"\bсколько\s+(стоит|стоят|стоить)\b",
    r"\bцен(а|у|ы)\b",
    r"\bпочём\b",
)
_PAYMENT = _r(
    r"\bhow\s+(do|can)\s+i\s+(pay|buy|purchase)\b",
    r"\b(payment\s+method|how\s+to\s+pay)\b",
    r"\b(stars|telegram\s+stars)\b",
    r"\bкак\s+(оплатить|купить|заплатить)\b",
)
# CONTENT_REQUEST: asks for media (photo/video/etc.). Does NOT require explicit sex.
_CONTENT = _r(
    r"\bsend\s+(me\s+)?(a\s+|some\s+)?(pic|pics|picture|photo|photos|video|vid|clip)\b",
    r"\bcan\s+i\s+(see|get|have)\s+.*(pic|photo|video|clip|content)\b",
    r"\b(more|another)\s+(pic|pics|photo|photos|video|vid)\b",
    r"\bпришли\s+(фото|видео|картинку|пикчу)\b",
    r"\bкиньт?е\s+(фото|видео)\b",
    r"\bпокажи\s+(фото|тело|сись?к|жоп)",
)
# SEXUAL_REQUEST: explicit asks. Adult, consensual; minors/non-consent live in safety layer.
_SEXUAL = _r(
    r"\b(send\s+(me\s+)?nude(s)?|nude(s)?\s+pls)\b",
    r"\b(jerk\s*off|cum|cock|dick|pussy|tits|boobs|fuck\s+(me|you|u)|sext|sexting)\b",
    r"\b(порн|секс\s+чат|дрочк|кончи|сись?к|трахн|трахаться)\b",
)
_COMPLAINT = _r(
    r"\b(refund|money\s+back|scam(med|mer)?|cheat(ed)?|liar|lied|ripped\s+off)\b",
    r"\b(this\s+is\s+(bs|bullshit|fake))\b",
    r"\b(возврат|обман|кидалово|развод|верни\s+деньги)\b",
)
_COMPLIMENT = _r(
    r"\byou(\s+are|'re|\s+r)\s+(so\s+)?(beautiful|hot|cute|sexy|gorgeous|pretty|stunning|amazing)\b",
    r"\b(you\s+look|love\s+your)\s+",
    r"\bты\s+(красив|симпатичн|очаровательн|шикарн|такая\s+красив)",
)
# PERSONAL_QUESTION: questions about HER (name, age, where from, what doing).
_PERSONAL = _r(
    r"\bwhere\s+are\s+you\s+(from|at|now)\b",
    r"\bhow\s+old\s+are\s+you\b",
    r"\bwhat('?s)?\s+your\s+(name|age|job)\b",
    r"\bwhat\s+(are\s+)?you\s+(doing|up\s+to)\b",
    r"\bоткуда\s+ты\b",
    r"\bсколько\s+(тебе\s+)?лет\b",
    r"\bкак\s+тебя\s+зовут\b",
    r"\bчто\s+делаешь\b",
)
_SMALLTALK = _r(
    r"\bhow('?s)?\s+(it\s+going|are\s+you|s\s+up|s\s+life)\b",
    r"\bwhat('?s)?\s+up\b",
    r"\b(как\s+(дела|жизнь|настроение)|чо\s+как)\b",
)


_ORDER: tuple[tuple[Intent, frozenset[re.Pattern[str]]], ...] = (
    # Highest priority first: clear transactional / safety-adjacent intents
    # win over greetings even when both match.
    (Intent.COMPLAINT, _COMPLAINT),
    (Intent.PAYMENT_QUESTION, _PAYMENT),
    (Intent.PRICE_QUESTION, _PRICE),
    (Intent.SEXUAL_REQUEST, _SEXUAL),
    (Intent.CONTENT_REQUEST, _CONTENT),
    (Intent.PERSONAL_QUESTION, _PERSONAL),
    (Intent.COMPLIMENT, _COMPLIMENT),
    (Intent.FAREWELL, _FAREWELL),
    (Intent.GREETING, _GREETING),
    (Intent.SMALLTALK, _SMALLTALK),
)


def classify_intent(text: str) -> IntentResult:
    """Return the most likely `Intent` for `text`.

    Empty / whitespace-only input → `UNKNOWN` with empty `matched`. Otherwise
    returns the highest-priority intent whose pattern matches; falls back to
    `UNKNOWN` if nothing matches.
    """
    if not text or not text.strip():
        return IntentResult(intent=Intent.UNKNOWN, confidence="low", matched=())

    matched_per_intent: list[tuple[Intent, list[str]]] = []
    for intent, patterns in _ORDER:
        hits: list[str] = []
        for p in patterns:
            if p.search(text):
                hits.append(p.pattern)
        if hits:
            matched_per_intent.append((intent, hits))

    if not matched_per_intent:
        return IntentResult(intent=Intent.UNKNOWN, confidence="low", matched=())

    # Highest-priority match (first one in `_ORDER`) wins.
    best_intent, hits = matched_per_intent[0]
    short = len(text.strip()) <= 40
    confidence = "high" if (short and best_intent != Intent.SMALLTALK) else "mid"
    return IntentResult(intent=best_intent, confidence=confidence, matched=tuple(hits))

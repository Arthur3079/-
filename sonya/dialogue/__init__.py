"""Dialogue orchestration: takes one incoming message, produces one reply.

The Telethon handler should be tiny: receive an event, persist the incoming
message, ask the orchestrator for a reply (`DialogueResult`), and either
send it or skip. All business logic — safety, retrieval, prompt assembly,
post-processing — lives in `DialogueService`.
"""

from sonya.dialogue.bubbles import split_into_bubbles
from sonya.dialogue.intent import Intent, IntentResult, classify_intent
from sonya.dialogue.result import DialogueResult, SkipReason
from sonya.dialogue.service import DialogueService

__all__ = [
    "DialogueResult",
    "DialogueService",
    "Intent",
    "IntentResult",
    "SkipReason",
    "classify_intent",
    "split_into_bubbles",
]

"""Return type of `DialogueService.handle_incoming`.

A single immutable record so the handler doesn't have to know how the reply
was produced — only what to do with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SkipReason(str, Enum):
    NONE = "none"
    SAFETY_PRE_BLOCK = "safety_pre_block"
    SAFETY_POST_BLOCK = "safety_post_block"
    LLM_NOT_CONFIGURED = "llm_not_configured"
    LLM_FAILED = "llm_failed"
    EMPTY_INCOMING = "empty_incoming"
    EMPTY_REPLY = "empty_reply"


@dataclass(frozen=True)
class DialogueResult:
    """Outcome of one dialogue turn.

    `reply_text` is what the handler should send (one logical message; if/when
    bubble-splitting lands it'll become a list). `None` means: do not send.
    `skipped_reason` tells the handler why we declined to produce a normal reply.
    `safety_flags` enumerates safety verdicts that fired (for events_log).
    `used_playbook` / `used_knowledge` are populated when retrieval picked
    snippets — useful for debugging "why did Sonya answer that way".
    """

    reply_text: str | None
    skipped_reason: SkipReason = SkipReason.NONE
    handoff_required: bool = False
    safety_flags: tuple[str, ...] = field(default_factory=tuple)
    used_playbook: str | None = None
    used_knowledge: tuple[str, ...] = field(default_factory=tuple)
    intent: str | None = None
    fan_type: str | None = None
    bubbles: tuple[str, ...] = field(default_factory=tuple)
    # When the sales engine decided to offer a content set this turn:
    offered_set_code: str | None = None
    invoice_payload: str | None = None

    @property
    def should_send(self) -> bool:
        return self.reply_text is not None and self.reply_text.strip() != ""

    @property
    def send_bubbles(self) -> tuple[str, ...]:
        """The actual sequence of strings to send.

        Falls back to a one-element tuple of `reply_text` if the orchestrator
        didn't populate `bubbles` (e.g. safety canned reply, stub mode).
        """
        if self.bubbles:
            return self.bubbles
        if self.reply_text:
            return (self.reply_text,)
        return ()

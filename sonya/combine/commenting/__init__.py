"""Combine module 3 — neuro-commenting.

Submits *campaigns*: per-channel rules + LLM prompt template + a pool of
accounts. The campaign's worker (Sprint 7) watches the channel for new
posts, picks an account, asks an LLM to draft a comment, schedules it,
and posts it under the source channel discussion.

This sprint ships the bookkeeping side and a deterministic stub
renderer used by tests and `/render-stub`.
"""

from sonya.combine.commenting.renderer import (
    CommentRenderer,
    RenderedComment,
    StubCommentRenderer,
)
from sonya.combine.commenting.telethon_poster import (
    PostedComment,
    TelethonCommentPoster,
)
from sonya.combine.commenting.worker_plugin import CommentingWorkerPlugin

__all__ = [
    "CommentRenderer",
    "CommentingWorkerPlugin",
    "PostedComment",
    "RenderedComment",
    "StubCommentRenderer",
    "TelethonCommentPoster",
]

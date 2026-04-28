"""Render an LLM-generated comment for an observed post.

Like the parsers module, the combine separates *intent* (REST creates a
campaign + spotted post) from *generation* (a worker calls the LLM).
This module ships only the contract + a deterministic offline renderer
used in tests and to smoke-test the `/render-stub` endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sonya.db.models_combine import (
    CommentingCampaign,
    ObservedPost,
)


@dataclass(frozen=True)
class RenderedComment:
    """A single LLM-rendered candidate comment."""

    text: str


class CommentRenderer(Protocol):
    """Strategy interface for generating comment text."""

    async def render(
        self, *, campaign: CommentingCampaign, post: ObservedPost
    ) -> RenderedComment:  # pragma: no cover - interface
        ...


class StubCommentRenderer:
    """Deterministic offline renderer.

    Implements the simplest possible substitution:
    ``prompt_template.format(post=post.text or '')``. Truncates to
    ``max_length`` and prefixes with a deterministic tag so tests can
    distinguish stub-rendered from real-LLM-rendered output.
    """

    def __init__(self, *, max_length: int = 280, tag: str = "[stub]") -> None:
        if max_length < 1:
            raise ValueError("max_length must be >= 1")
        self._max_length = max_length
        self._tag = tag

    async def render(self, *, campaign: CommentingCampaign, post: ObservedPost) -> RenderedComment:
        body = (post.text or "").strip()
        try:
            prompt = campaign.prompt_template.format(post=body)
        except KeyError:
            prompt = campaign.prompt_template
        text = f"{self._tag} {prompt}".strip()
        if len(text) > self._max_length:
            text = text[: self._max_length - 1].rstrip() + "…"
        return RenderedComment(text=text)


__all__ = ["CommentRenderer", "RenderedComment", "StubCommentRenderer"]

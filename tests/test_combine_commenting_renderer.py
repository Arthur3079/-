"""Unit tests for `StubCommentRenderer`."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sonya.combine.commenting.renderer import StubCommentRenderer
from sonya.db.models_combine import (
    CommentingCampaign,
    CommentingCampaignStatus,
    ObservedPost,
    ObservedPostStatus,
)


def _campaign(prompt: str) -> CommentingCampaign:
    c = CommentingCampaign()
    c.id = 1
    c.owner_id = 1
    c.name = "test"
    c.prompt_template = prompt
    c.target_channels = []
    c.account_ids = []
    c.min_delay_seconds = 60
    c.max_delay_seconds = 300
    c.max_comments_per_day = 20
    c.status = CommentingCampaignStatus.DRAFT
    return c


def _post(text: str | None) -> ObservedPost:
    p = ObservedPost()
    p.id = 1
    p.campaign_id = 1
    p.channel = "@news"
    p.tg_message_id = 100
    p.text = text
    p.status = ObservedPostStatus.NEW
    p.observed_at = datetime.now(timezone.utc)
    return p


@pytest.mark.asyncio
async def test_render_substitutes_post_text() -> None:
    out = await StubCommentRenderer().render(
        campaign=_campaign("Reply to: {post}"),
        post=_post("BTC to the moon"),
    )
    assert "BTC to the moon" in out.text
    assert out.text.startswith("[stub]")


@pytest.mark.asyncio
async def test_render_handles_missing_placeholder() -> None:
    out = await StubCommentRenderer().render(
        campaign=_campaign("Generic reply"),
        post=_post(None),
    )
    assert out.text == "[stub] Generic reply"


@pytest.mark.asyncio
async def test_render_truncates_to_max_length() -> None:
    long_post = "x" * 1000
    out = await StubCommentRenderer(max_length=50).render(
        campaign=_campaign("Reply: {post}"),
        post=_post(long_post),
    )
    assert len(out.text) == 50
    assert out.text.endswith("…")


@pytest.mark.asyncio
async def test_render_handles_unknown_template_keys_gracefully() -> None:
    out = await StubCommentRenderer().render(
        campaign=_campaign("Hello {unknown_key}"),
        post=_post("text"),
    )
    # Falls back to the raw template — must not raise.
    assert "Hello {unknown_key}" in out.text


def test_max_length_must_be_positive() -> None:
    with pytest.raises(ValueError):
        StubCommentRenderer(max_length=0)

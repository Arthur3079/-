"""Unit tests for :class:`TelethonCommentPoster` against a fake client."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from sonya.combine.commenting.telethon_poster import TelethonCommentPoster


@dataclass
class _FakeMessage:
    id: int


@dataclass
class _FakeClient:
    sent: list[dict[str, Any]] = field(default_factory=list)
    next_message_id: int = 4242

    async def send_message(self, **kwargs: Any) -> _FakeMessage:
        self.sent.append(kwargs)
        return _FakeMessage(id=self.next_message_id)


@pytest.mark.asyncio
async def test_poster_calls_send_message_with_comment_to() -> None:
    client = _FakeClient(next_message_id=999)
    poster = TelethonCommentPoster()

    result = await poster.post(client, "@channel", 100, "hello world")

    assert result.tg_comment_id == 999
    assert len(client.sent) == 1
    call = client.sent[0]
    assert call["entity"] == "@channel"
    assert call["message"] == "hello world"
    assert call["comment_to"] == 100


@pytest.mark.asyncio
async def test_poster_returns_int_message_id() -> None:
    """Telethon's Message.id is an int — the dataclass mirrors that."""
    client = _FakeClient(next_message_id=12345)
    poster = TelethonCommentPoster()

    result = await poster.post(client, "@news", 50, "comment")

    assert isinstance(result.tg_comment_id, int)
    assert result.tg_comment_id == 12345

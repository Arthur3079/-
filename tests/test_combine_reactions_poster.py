"""Unit tests for :class:`TelethonReactionPoster` with a fake client."""

from __future__ import annotations

from typing import Any

import pytest

from sonya.combine.reactions.telethon_poster import TelethonReactionPoster


class FakeClient:
    """Captures raw Telethon requests issued via ``client(request)``."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def __call__(self, request: Any) -> None:
        self.calls.append(request)


@pytest.mark.asyncio
async def test_post_sends_send_reaction_request() -> None:
    client = FakeClient()
    poster = TelethonReactionPoster()

    await poster.post(client, channel="test_channel", tg_message_id=42, emoji="\U0001f525")

    assert len(client.calls) == 1
    req = client.calls[0]

    # Verify the Telethon request type and fields.
    from telethon.tl.functions.messages import SendReactionRequest
    from telethon.tl.types import ReactionEmoji

    assert isinstance(req, SendReactionRequest)
    assert req.peer == "test_channel"
    assert req.msg_id == 42
    assert len(req.reaction) == 1
    assert isinstance(req.reaction[0], ReactionEmoji)
    assert req.reaction[0].emoticon == "\U0001f525"


@pytest.mark.asyncio
async def test_post_propagates_client_error() -> None:
    class ErrorClient:
        async def __call__(self, request: Any) -> None:
            raise RuntimeError("Telegram API error")

    poster = TelethonReactionPoster()
    with pytest.raises(RuntimeError, match="Telegram API error"):
        await poster.post(ErrorClient(), channel="ch", tg_message_id=1, emoji="\u2764\ufe0f")

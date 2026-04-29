"""Post a single emoji reaction via Telethon raw API."""

from __future__ import annotations

from typing import Any


class TelethonReactionPoster:
    """Wraps ``SendReactionRequest`` so callers don't import Telethon directly."""

    async def post(
        self,
        client: Any,
        channel: Any,
        tg_message_id: int,
        emoji: str,
    ) -> None:
        """Send *emoji* as a reaction to *tg_message_id* in *channel*."""

        from telethon.tl.functions.messages import SendReactionRequest
        from telethon.tl.types import ReactionEmoji

        await client(
            SendReactionRequest(
                peer=channel,
                msg_id=tg_message_id,
                reaction=[ReactionEmoji(emoticon=emoji)],
            )
        )


__all__ = ["TelethonReactionPoster"]

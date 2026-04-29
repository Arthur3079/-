"""Post a single comment as a reply to a channel post via Telethon."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PostedComment:
    """Result of a successful comment post."""

    tg_comment_id: int


class TelethonCommentPoster:
    """Wraps :meth:`TelegramClient.send_message` with ``comment_to=...``.

    Telethon resolves the channel's linked discussion group automatically
    when ``comment_to`` is set, so callers only need the source channel
    + post id.
    """

    async def post(
        self,
        client: Any,
        channel: Any,
        tg_message_id: int,
        text: str,
    ) -> PostedComment:
        """Send *text* as a reply-comment under *tg_message_id* in *channel*.

        Returns the posted message id (the comment's ``message.id`` in the
        discussion group, which the caller stores on the
        :class:`Comment` row).
        """

        message = await client.send_message(
            entity=channel,
            message=text,
            comment_to=tg_message_id,
        )
        return PostedComment(tg_comment_id=int(message.id))


__all__ = ["PostedComment", "TelethonCommentPoster"]

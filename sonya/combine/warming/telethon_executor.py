"""Execute one :class:`WarmingAction` against a live Telethon client.

Mapping ``WarmingActionKind`` → Telethon call:

* ``SUBSCRIBE_CHANNEL`` → :class:`JoinChannelRequest`
* ``READ_HISTORY``      → ``client.get_messages(...)`` + ``send_read_acknowledge``
* ``REACT_POST``        → :class:`SendReactionRequest` on the latest message
* ``SEND_IDLE_MESSAGE`` → ``client.send_message("me", ...)`` to Saved Messages
                          (intentionally innocuous — counts as account
                          activity without poking strangers)

The executor is intentionally side-effect-only: it returns ``None`` on
success and lets exceptions propagate so the worker plugin can
distinguish FloodWait from generic failures.
"""

from __future__ import annotations

from typing import Any

from sonya.db.models_combine import WarmingAction, WarmingActionKind

DEFAULT_REACT_EMOJI = "👍"
DEFAULT_IDLE_MESSAGE = "."
HISTORY_PEEK_LIMIT = 20


class TelethonWarmingExecutor:
    """Run one warming action through a Telethon ``client``."""

    def __init__(
        self,
        *,
        react_emoji: str = DEFAULT_REACT_EMOJI,
        idle_message: str = DEFAULT_IDLE_MESSAGE,
        history_limit: int = HISTORY_PEEK_LIMIT,
    ) -> None:
        self._react_emoji = react_emoji
        self._idle_message = idle_message
        self._history_limit = history_limit

    async def execute(self, client: Any, action: WarmingAction) -> None:
        """Execute *action* — raise on failure, return ``None`` on success."""

        kind = action.kind
        if kind == WarmingActionKind.SUBSCRIBE_CHANNEL:
            await self._subscribe(client, action.target)
            return
        if kind == WarmingActionKind.READ_HISTORY:
            await self._read_history(client, action.target)
            return
        if kind == WarmingActionKind.REACT_POST:
            await self._react(client, action.target)
            return
        if kind == WarmingActionKind.SEND_IDLE_MESSAGE:
            await self._send_idle(client)
            return
        raise ValueError(f"unknown warming action kind: {kind!r}")

    # ---- per-kind helpers ----

    async def _subscribe(self, client: Any, target: str | None) -> None:
        if not target:
            raise ValueError("SUBSCRIBE_CHANNEL requires a target")
        from telethon.tl.functions.channels import JoinChannelRequest

        await client(JoinChannelRequest(channel=target))

    async def _read_history(self, client: Any, target: str | None) -> None:
        if not target:
            raise ValueError("READ_HISTORY requires a target")
        messages = await client.get_messages(target, limit=self._history_limit)
        # ``send_read_acknowledge`` accepts the peer + the latest message.
        if messages:
            try:
                await client.send_read_acknowledge(target, message=messages[0])
            except Exception:
                # Reading is best-effort — failing to ack should not fail
                # the warming action since the activity already happened.
                pass

    async def _react(self, client: Any, target: str | None) -> None:
        if not target:
            raise ValueError("REACT_POST requires a target")
        from telethon.tl.functions.messages import SendReactionRequest
        from telethon.tl.types import ReactionEmoji

        # Pick the latest visible message in the channel and react to it.
        messages = await client.get_messages(target, limit=1)
        if not messages:
            raise RuntimeError(f"no messages found in {target!r} to react to")
        latest = messages[0]
        await client(
            SendReactionRequest(
                peer=target,
                msg_id=int(latest.id),
                reaction=[ReactionEmoji(emoticon=self._react_emoji)],
            )
        )

    async def _send_idle(self, client: Any) -> None:
        await client.send_message("me", self._idle_message)


__all__ = [
    "DEFAULT_IDLE_MESSAGE",
    "DEFAULT_REACT_EMOJI",
    "HISTORY_PEEK_LIMIT",
    "TelethonWarmingExecutor",
]

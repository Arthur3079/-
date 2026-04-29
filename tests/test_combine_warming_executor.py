"""Unit tests for :class:`TelethonWarmingExecutor` against a fake client."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest

from sonya.combine.warming.telethon_executor import (
    DEFAULT_IDLE_MESSAGE,
    DEFAULT_REACT_EMOJI,
    TelethonWarmingExecutor,
)
from sonya.db.models_combine import WarmingAction, WarmingActionKind


@dataclass
class _FakeMessage:
    id: int


@dataclass
class _FakeClient:
    raw_calls: list[Any] = field(default_factory=list)
    sent_messages: list[tuple[Any, str]] = field(default_factory=list)
    history_calls: list[tuple[Any, int]] = field(default_factory=list)
    read_acks: list[tuple[Any, int]] = field(default_factory=list)
    history: list[_FakeMessage] = field(default_factory=lambda: [_FakeMessage(id=99)])
    read_ack_raises: Exception | None = None

    async def __call__(self, request: Any) -> None:
        self.raw_calls.append(request)

    async def get_messages(self, peer: Any, limit: int = 1) -> list[_FakeMessage]:
        self.history_calls.append((peer, limit))
        return list(self.history)

    async def send_read_acknowledge(self, peer: Any, *, message: _FakeMessage) -> None:
        if self.read_ack_raises is not None:
            raise self.read_ack_raises
        self.read_acks.append((peer, message.id))

    async def send_message(self, peer: Any, text: str) -> None:
        self.sent_messages.append((peer, text))


def _action(kind: WarmingActionKind, target: str | None = None) -> WarmingAction:
    return WarmingAction(
        id=1,
        job_id=1,
        kind=kind,
        target=target,
        scheduled_at=datetime.now(timezone.utc),
        status=None,  # type: ignore[arg-type]
        trust_delta=1,
    )


@pytest.mark.asyncio
async def test_subscribe_channel_calls_join_request() -> None:
    client = _FakeClient()
    exe = TelethonWarmingExecutor()
    await exe.execute(client, _action(WarmingActionKind.SUBSCRIBE_CHANNEL, "@news"))
    assert len(client.raw_calls) == 1
    assert type(client.raw_calls[0]).__name__ == "JoinChannelRequest"


@pytest.mark.asyncio
async def test_subscribe_channel_requires_target() -> None:
    client = _FakeClient()
    exe = TelethonWarmingExecutor()
    with pytest.raises(ValueError, match="SUBSCRIBE_CHANNEL"):
        await exe.execute(client, _action(WarmingActionKind.SUBSCRIBE_CHANNEL))


@pytest.mark.asyncio
async def test_read_history_fetches_and_acks() -> None:
    client = _FakeClient(history=[_FakeMessage(id=42)])
    exe = TelethonWarmingExecutor(history_limit=5)
    await exe.execute(client, _action(WarmingActionKind.READ_HISTORY, "@news"))
    assert client.history_calls == [("@news", 5)]
    assert client.read_acks == [("@news", 42)]


@pytest.mark.asyncio
async def test_read_history_swallows_ack_errors() -> None:
    """Ack failure should not bubble up — the read activity already happened."""
    client = _FakeClient(read_ack_raises=RuntimeError("boom"))
    exe = TelethonWarmingExecutor()
    # Must not raise
    await exe.execute(client, _action(WarmingActionKind.READ_HISTORY, "@news"))


@pytest.mark.asyncio
async def test_read_history_skips_ack_when_empty() -> None:
    client = _FakeClient(history=[])
    exe = TelethonWarmingExecutor()
    await exe.execute(client, _action(WarmingActionKind.READ_HISTORY, "@news"))
    assert client.read_acks == []


@pytest.mark.asyncio
async def test_react_post_calls_send_reaction_request() -> None:
    client = _FakeClient(history=[_FakeMessage(id=77)])
    exe = TelethonWarmingExecutor()
    await exe.execute(client, _action(WarmingActionKind.REACT_POST, "@news"))
    assert len(client.raw_calls) == 1
    req = client.raw_calls[0]
    assert type(req).__name__ == "SendReactionRequest"
    assert req.msg_id == 77


@pytest.mark.asyncio
async def test_react_post_with_no_messages_raises() -> None:
    client = _FakeClient(history=[])
    exe = TelethonWarmingExecutor()
    with pytest.raises(RuntimeError, match="no messages"):
        await exe.execute(client, _action(WarmingActionKind.REACT_POST, "@news"))


@pytest.mark.asyncio
async def test_send_idle_message_to_self() -> None:
    client = _FakeClient()
    exe = TelethonWarmingExecutor()
    await exe.execute(client, _action(WarmingActionKind.SEND_IDLE_MESSAGE))
    assert client.sent_messages == [("me", DEFAULT_IDLE_MESSAGE)]


@pytest.mark.asyncio
async def test_send_idle_message_uses_custom_text() -> None:
    client = _FakeClient()
    exe = TelethonWarmingExecutor(idle_message="ping")
    await exe.execute(client, _action(WarmingActionKind.SEND_IDLE_MESSAGE))
    assert client.sent_messages == [("me", "ping")]


@pytest.mark.asyncio
async def test_default_react_emoji_is_thumbs_up() -> None:
    """Sanity check on the constant used in real prod calls."""
    assert DEFAULT_REACT_EMOJI == "👍"

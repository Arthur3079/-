"""Unit tests for :class:`TelethonExecutor` with a fake TelegramClient."""

from __future__ import annotations

from typing import Any

import pytest

from sonya.combine.parsers.telethon_executor import TelethonExecutor
from sonya.db.models_combine import (
    Account,
    AccountRole,
    AccountStatus,
    ParserJob,
    ParserJobStatus,
    ParserKind,
    ParserResultKind,
)

# ------------------------------------------------------------------
# Fake Telethon objects
# ------------------------------------------------------------------


class FakeUser:
    def __init__(
        self,
        *,
        id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> None:
        self.id = id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name


class FakeDialog:
    def __init__(self, *, is_channel: bool = False, entity: Any = None) -> None:
        self.is_channel = is_channel
        self.entity = entity


class FakeEntity:
    def __init__(
        self,
        *,
        id: int,
        username: str | None = None,
        title: str | None = None,
    ) -> None:
        self.id = id
        self.username = username
        self.title = title


class FakeMessage:
    def __init__(
        self,
        *,
        id: int,
        text: str | None = None,
        sender_id: int | None = None,
        sender: Any = None,
    ) -> None:
        self.id = id
        self.text = text
        self.sender_id = sender_id
        self.sender = sender


class FakeTelegramClient:
    """Minimal fake that yields preset data for each iter_* method."""

    def __init__(
        self,
        *,
        participants: list[FakeUser] | None = None,
        dialogs: list[FakeDialog] | None = None,
        messages: list[FakeMessage] | None = None,
    ) -> None:
        self._participants = participants or []
        self._dialogs = dialogs or []
        self._messages = messages or []

    async def iter_participants(self, chat: Any) -> Any:  # noqa: ANN401
        for u in self._participants:
            yield u

    async def iter_dialogs(self) -> Any:  # noqa: ANN401
        for d in self._dialogs:
            yield d

    async def iter_messages(self, peer: Any, *, limit: int = 100, search: str = "") -> Any:  # noqa: ANN401
        for m in self._messages[:limit]:
            yield m

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _account(account_id: int = 1) -> Account:
    acc = Account()
    acc.id = account_id
    acc.owner_id = 1
    acc.phone = "+10000000001"
    acc.role = AccountRole.PARSER
    acc.status = AccountStatus.ACTIVE
    return acc


def _job(
    kind: ParserKind,
    target: str = "test_target",
    params: dict[str, object] | None = None,
) -> ParserJob:
    job = ParserJob()
    job.id = 1
    job.owner_id = 1
    job.account_id = 1
    job.kind = kind
    job.target = target
    job.params = params or {}
    job.status = ParserJobStatus.RUNNING
    job.result_count = 0
    return job


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_users_in_chat() -> None:
    users = [
        FakeUser(id=100, username="alice", first_name="Alice", last_name="A"),
        FakeUser(id=101, username="bob", first_name="Bob"),
    ]
    client = FakeTelegramClient(participants=users)
    executor = TelethonExecutor()
    job = _job(ParserKind.USERS_IN_CHAT, target="my_chat")
    results = await executor.run(job, _account(), client=client)

    assert len(results) == 2
    assert all(r.kind == ParserResultKind.USER for r in results)
    assert results[0].tg_id == 100
    assert results[0].username == "alice"
    assert results[0].title == "Alice A"
    assert results[0].extra == {"chat": "my_chat"}
    assert results[1].tg_id == 101
    assert results[1].title == "Bob"


@pytest.mark.asyncio
async def test_channels_of_user() -> None:
    entity_a = FakeEntity(id=200, username="chan_a", title="Channel A")
    entity_b = FakeEntity(id=201, username="chan_b", title="Channel B")
    dialogs = [
        FakeDialog(is_channel=True, entity=entity_a),
        FakeDialog(is_channel=False, entity=FakeEntity(id=999)),
        FakeDialog(is_channel=True, entity=entity_b),
    ]
    client = FakeTelegramClient(dialogs=dialogs)
    executor = TelethonExecutor()
    job = _job(ParserKind.CHANNELS_OF_USER, target="user_123")
    results = await executor.run(job, _account(), client=client)

    assert len(results) == 2
    assert all(r.kind == ParserResultKind.CHANNEL for r in results)
    assert results[0].tg_id == 200
    assert results[0].title == "Channel A"
    assert results[0].extra == {"user": "user_123"}
    assert results[1].tg_id == 201


@pytest.mark.asyncio
async def test_chat_history() -> None:
    messages = [
        FakeMessage(id=300, text="Hello world", sender_id=10),
        FakeMessage(id=301, text="Goodbye", sender_id=11),
    ]
    client = FakeTelegramClient(messages=messages)
    executor = TelethonExecutor()
    job = _job(ParserKind.CHAT_HISTORY, target="peer_x", params={"limit": 50})
    results = await executor.run(job, _account(), client=client)

    assert len(results) == 2
    assert all(r.kind == ParserResultKind.MESSAGE for r in results)
    assert results[0].tg_id == 300
    assert results[0].title == "Hello world"
    assert results[0].extra == {"peer": "peer_x", "sender_id": 10}


@pytest.mark.asyncio
async def test_users_by_message() -> None:
    sender = FakeUser(id=400, username="poster_a", first_name="Poster")
    messages = [
        FakeMessage(id=500, text="match1", sender_id=400, sender=sender),
        FakeMessage(id=501, text="match2", sender_id=400, sender=sender),
        FakeMessage(
            id=502, text="match3", sender_id=401, sender=FakeUser(id=401, username="poster_b")
        ),
    ]
    client = FakeTelegramClient(messages=messages)
    executor = TelethonExecutor()
    job = _job(
        ParserKind.USERS_BY_MESSAGE,
        target="peer_y",
        params={"query": "match", "limit": 100},
    )
    results = await executor.run(job, _account(), client=client)

    # sender_id=400 appears twice but should be deduplicated.
    assert len(results) == 2
    assert all(r.kind == ParserResultKind.USER for r in results)
    assert results[0].tg_id == 400
    assert results[0].username == "poster_a"
    assert results[1].tg_id == 401


@pytest.mark.asyncio
async def test_empty_results() -> None:
    client = FakeTelegramClient()
    executor = TelethonExecutor()
    for kind in ParserKind:
        job = _job(kind, target="empty")
        results = await executor.run(job, _account(), client=client)
        assert results == []

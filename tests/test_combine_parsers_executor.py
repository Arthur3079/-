"""Unit tests for `StubParserExecutor`."""

from __future__ import annotations

import pytest

from sonya.combine.parsers.executor import StubParserExecutor
from sonya.db.models_combine import (
    Account,
    AccountRole,
    AccountStatus,
    ParserJob,
    ParserJobStatus,
    ParserKind,
    ParserResultKind,
)


def _job(kind: ParserKind, target: str, **params: object) -> ParserJob:
    job = ParserJob()
    job.id = 1
    job.owner_id = 1
    job.account_id = 1
    job.kind = kind
    job.target = target
    job.params = params or {}
    job.status = ParserJobStatus.PENDING
    job.result_count = 0
    return job


def _account() -> Account:
    acc = Account()
    acc.id = 1
    acc.owner_id = 1
    acc.phone = "+10000000000"
    acc.role = AccountRole.MULTI
    acc.status = AccountStatus.ACTIVE
    return acc


@pytest.mark.asyncio
async def test_users_in_chat_emits_user_results() -> None:
    exec_ = StubParserExecutor(batch_size=3)
    out = await exec_.run(_job(ParserKind.USERS_IN_CHAT, "telegram"), _account())
    assert len(out) == 3
    assert all(r.kind == ParserResultKind.USER for r in out)
    assert {r.username for r in out} == {"member_0", "member_1", "member_2"}
    assert all(r.extra["chat"] == "telegram" for r in out)


@pytest.mark.asyncio
async def test_channels_of_user_emits_channel_results() -> None:
    exec_ = StubParserExecutor()
    out = await exec_.run(_job(ParserKind.CHANNELS_OF_USER, "@durov"), _account())
    assert all(r.kind == ParserResultKind.CHANNEL for r in out)
    assert all(r.extra["user"] == "@durov" for r in out)


@pytest.mark.asyncio
async def test_chat_history_emits_message_results() -> None:
    exec_ = StubParserExecutor()
    out = await exec_.run(_job(ParserKind.CHAT_HISTORY, "@durov", limit=2), _account())
    assert len(out) == 2
    assert all(r.kind == ParserResultKind.MESSAGE for r in out)


@pytest.mark.asyncio
async def test_users_by_message_returns_users_with_query_match() -> None:
    exec_ = StubParserExecutor()
    out = await exec_.run(_job(ParserKind.USERS_BY_MESSAGE, "crypto"), _account())
    assert all(r.kind == ParserResultKind.USER for r in out)
    assert all(r.extra["query"] == "crypto" for r in out)


@pytest.mark.asyncio
async def test_limit_param_overrides_default_batch_size() -> None:
    exec_ = StubParserExecutor(batch_size=5)
    out = await exec_.run(_job(ParserKind.USERS_IN_CHAT, "x", limit=12), _account())
    assert len(out) == 12


def test_batch_size_must_be_positive() -> None:
    with pytest.raises(ValueError):
        StubParserExecutor(batch_size=0)


@pytest.mark.asyncio
async def test_limit_clamped_to_max_100() -> None:
    exec_ = StubParserExecutor()
    out = await exec_.run(_job(ParserKind.USERS_IN_CHAT, "x", limit=500), _account())
    assert len(out) == 100

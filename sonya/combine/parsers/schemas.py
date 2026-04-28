"""Pydantic schemas for the combine `parsers` REST API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from sonya.db.models_combine import (
    ParserJobStatus,
    ParserKind,
    ParserResultKind,
)


class ParserJobCreateIn(BaseModel):
    account_id: int
    kind: ParserKind
    target: str = Field(min_length=1, max_length=255)
    params: dict[str, object] = Field(default_factory=dict)
    note: str | None = None


class ParserJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    account_id: int
    kind: ParserKind
    target: str
    status: ParserJobStatus
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    result_count: int
    note: str | None


class ParserResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    kind: ParserResultKind
    tg_id: int | None
    username: str | None
    title: str | None
    extra: dict[str, object]


class ParserResultsPage(BaseModel):
    items: list[ParserResultOut]
    total: int
    offset: int
    limit: int


class ParserResultIn(BaseModel):
    """Single result row pushed by the executor (or a manual operator)."""

    kind: ParserResultKind
    tg_id: int | None = None
    username: str | None = None
    title: str | None = None
    extra: dict[str, object] = Field(default_factory=dict)


class ParserResultsBatchIn(BaseModel):
    results: list[ParserResultIn]


class ParserJobCompleteIn(BaseModel):
    success: bool = True
    error: str | None = None


class ParserRunStubIn(BaseModel):
    """Run the deterministic ``StubParserExecutor`` against the job.

    Useful for smoke-tests / dev environments where there is no logged-in
    Telegram account yet.
    """

    batch_size: int | None = Field(default=None, ge=1, le=100)


__all__ = [
    "ParserJobCompleteIn",
    "ParserJobCreateIn",
    "ParserJobOut",
    "ParserResultIn",
    "ParserResultOut",
    "ParserResultsBatchIn",
    "ParserResultsPage",
    "ParserRunStubIn",
]

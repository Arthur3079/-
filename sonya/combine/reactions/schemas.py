"""Pydantic schemas for the combine `reactions` REST API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from sonya.db.models_combine import (
    ReactionCampaignStatus,
    ReactionStatus,
    ReactionTargetStatus,
)


class ReactionCampaignCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_channels: list[str] = Field(default_factory=list)
    account_ids: list[int] = Field(default_factory=list)
    emojis: list[str] = Field(default_factory=list)
    accounts_per_post: int = Field(default=3, ge=1, le=200)
    max_reactions_per_day: int = Field(default=200, ge=0, le=100000)
    note: str | None = None


class ReactionCampaignUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    target_channels: list[str] | None = None
    account_ids: list[int] | None = None
    emojis: list[str] | None = None
    accounts_per_post: int | None = Field(default=None, ge=1, le=200)
    max_reactions_per_day: int | None = Field(default=None, ge=0, le=100000)
    note: str | None = None


class ReactionCampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    status: ReactionCampaignStatus
    target_channels: list[str]
    account_ids: list[int]
    emojis: list[str]
    accounts_per_post: int
    max_reactions_per_day: int
    started_at: datetime | None
    paused_at: datetime | None
    archived_at: datetime | None
    note: str | None


class ReactionTargetIn(BaseModel):
    channel: str = Field(min_length=1, max_length=255)
    tg_message_id: int


class ReactionTargetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    channel: str
    tg_message_id: int
    status: ReactionTargetStatus
    observed_at: datetime


class ReactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_id: int
    account_id: int
    emoji: str
    status: ReactionStatus
    scheduled_at: datetime | None
    posted_at: datetime | None
    error: str | None


class ReactionRecordIn(BaseModel):
    """Outcome of a single posting attempt — pushed by the worker."""

    success: bool = True
    error: str | None = None


__all__ = [
    "ReactionCampaignCreateIn",
    "ReactionCampaignOut",
    "ReactionCampaignUpdateIn",
    "ReactionOut",
    "ReactionRecordIn",
    "ReactionTargetIn",
    "ReactionTargetOut",
]

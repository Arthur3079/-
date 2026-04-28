"""Pydantic schemas for the combine `commenting` REST API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from sonya.db.models_combine import (
    CommentingCampaignStatus,
    CommentStatus,
    ObservedPostStatus,
)


class CampaignCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt_template: str = Field(min_length=1)
    target_channels: list[str] = Field(default_factory=list)
    account_ids: list[int] = Field(default_factory=list)
    min_delay_seconds: int = Field(default=60, ge=0, le=3600)
    max_delay_seconds: int = Field(default=300, ge=0, le=86400)
    max_comments_per_day: int = Field(default=20, ge=0, le=10000)
    note: str | None = None


class CampaignUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    prompt_template: str | None = None
    target_channels: list[str] | None = None
    account_ids: list[int] | None = None
    min_delay_seconds: int | None = Field(default=None, ge=0, le=3600)
    max_delay_seconds: int | None = Field(default=None, ge=0, le=86400)
    max_comments_per_day: int | None = Field(default=None, ge=0, le=10000)
    note: str | None = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    status: CommentingCampaignStatus
    target_channels: list[str]
    account_ids: list[int]
    prompt_template: str
    min_delay_seconds: int
    max_delay_seconds: int
    max_comments_per_day: int
    started_at: datetime | None
    paused_at: datetime | None
    archived_at: datetime | None
    note: str | None


class ObservedPostIn(BaseModel):
    channel: str = Field(min_length=1, max_length=255)
    tg_message_id: int
    text: str | None = None


class ObservedPostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    channel: str
    tg_message_id: int
    text: str | None
    status: ObservedPostStatus
    observed_at: datetime


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    post_id: int
    account_id: int
    text: str | None
    status: CommentStatus
    scheduled_at: datetime | None
    posted_at: datetime | None
    error: str | None
    tg_comment_id: int | None


class CommentRecordIn(BaseModel):
    """Result of an external posting attempt — pushed by the worker."""

    success: bool = True
    text: str | None = None
    tg_comment_id: int | None = None
    error: str | None = None


class RenderStubIn(BaseModel):
    account_id: int
    max_length: int | None = Field(default=None, ge=1, le=4096)


__all__ = [
    "CampaignCreateIn",
    "CampaignOut",
    "CampaignUpdateIn",
    "CommentOut",
    "CommentRecordIn",
    "ObservedPostIn",
    "ObservedPostOut",
    "RenderStubIn",
]

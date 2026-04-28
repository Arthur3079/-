"""Pydantic response models for the combine analytics module.

All models are read-only snapshots — no inputs, no IDs, just numbers and a
small ``top``-list per module for quick triage on the dashboard.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StatusCount(BaseModel):
    """``COUNT(*) GROUP BY status`` row."""

    model_config = ConfigDict(frozen=True)

    status: str
    count: int = Field(ge=0)


class KindStatusCount(BaseModel):
    """``COUNT(*) GROUP BY (kind, status)`` row.

    Used for warming actions (kind = SUBSCRIBE_CHANNEL/READ_HISTORY/...) and
    parser jobs/results (kind = USERS_IN_CHAT/CHAT_HISTORY/...).
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    status: str
    count: int = Field(ge=0)


class KindCount(BaseModel):
    """``COUNT(*) GROUP BY kind`` row (no status dimension)."""

    model_config = ConfigDict(frozen=True)

    kind: str
    count: int = Field(ge=0)


class EmojiStatusCount(BaseModel):
    """``COUNT(*) GROUP BY (emoji, status)`` row for reactions."""

    model_config = ConfigDict(frozen=True)

    emoji: str
    status: str
    count: int = Field(ge=0)


class TrustBucket(BaseModel):
    """A single bucket of the ``trust_score`` histogram.

    Buckets are half-open ``[lower, upper)`` except the last one which is
    closed on both ends so that ``trust_score == 100`` lands somewhere.
    """

    model_config = ConfigDict(frozen=True)

    lower: int = Field(ge=0, le=100)
    upper: int = Field(ge=0, le=100)
    count: int = Field(ge=0)


class AccountTopRow(BaseModel):
    """Compact identity + trust for the top-N table on the dashboard."""

    model_config = ConfigDict(frozen=True)

    id: int
    phone: str
    status: str
    trust_score: int = Field(ge=0, le=100)


class CommentingCampaignTopRow(BaseModel):
    """Top-N campaign line for the commenting dashboard."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    status: str
    posted_count: int = Field(ge=0)


class ReactionCampaignTopRow(BaseModel):
    """Top-N campaign line for the reactions dashboard."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    status: str
    posted_count: int = Field(ge=0)


# ---------- per-module summaries ----------


class AccountsSummary(BaseModel):
    """Snapshot for the ``accounts`` (+ ``proxies``) module."""

    model_config = ConfigDict(frozen=True)

    total: int = Field(ge=0)
    by_status: list[StatusCount]
    avg_trust: float = Field(ge=0)
    min_trust: int = Field(ge=0, le=100)
    max_trust: int = Field(ge=0, le=100)
    trust_buckets: list[TrustBucket]
    top: list[AccountTopRow]
    proxies_total: int = Field(ge=0)
    proxies_by_health: list[StatusCount]


class WarmingSummary(BaseModel):
    """Snapshot for the warming module."""

    model_config = ConfigDict(frozen=True)

    jobs_total: int = Field(ge=0)
    jobs_by_status: list[StatusCount]
    actions_total: int = Field(ge=0)
    actions_by_kind_status: list[KindStatusCount]


class ParsersSummary(BaseModel):
    """Snapshot for the parsers module."""

    model_config = ConfigDict(frozen=True)

    jobs_total: int = Field(ge=0)
    jobs_by_status: list[StatusCount]
    jobs_by_kind: list[KindCount]
    results_total: int = Field(ge=0)
    results_by_kind: list[KindCount]
    results_by_job_kind: list[KindCount]


class CommentingSummary(BaseModel):
    """Snapshot for the commenting module."""

    model_config = ConfigDict(frozen=True)

    campaigns_total: int = Field(ge=0)
    campaigns_by_status: list[StatusCount]
    posts_total: int = Field(ge=0)
    posts_by_status: list[StatusCount]
    comments_total: int = Field(ge=0)
    comments_by_status: list[StatusCount]
    top: list[CommentingCampaignTopRow]


class ReactionsSummary(BaseModel):
    """Snapshot for the mass-reactions module."""

    model_config = ConfigDict(frozen=True)

    campaigns_total: int = Field(ge=0)
    campaigns_by_status: list[StatusCount]
    targets_total: int = Field(ge=0)
    targets_by_status: list[StatusCount]
    reactions_total: int = Field(ge=0)
    reactions_by_status: list[StatusCount]
    reactions_by_emoji_status: list[EmojiStatusCount]
    top: list[ReactionCampaignTopRow]


class OverallSummary(BaseModel):
    """One-shot snapshot used by the dashboard's hero card."""

    model_config = ConfigDict(frozen=True)

    accounts: AccountsSummary
    warming: WarmingSummary
    parsers: ParsersSummary
    commenting: CommentingSummary
    reactions: ReactionsSummary


__all__ = [
    "AccountTopRow",
    "AccountsSummary",
    "CommentingCampaignTopRow",
    "CommentingSummary",
    "EmojiStatusCount",
    "KindCount",
    "KindStatusCount",
    "OverallSummary",
    "ParsersSummary",
    "ReactionCampaignTopRow",
    "ReactionsSummary",
    "StatusCount",
    "TrustBucket",
    "WarmingSummary",
]

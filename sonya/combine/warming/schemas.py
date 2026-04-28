"""Pydantic schemas for the combine `warming` REST API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from sonya.db.models_combine import (
    WarmingActionKind,
    WarmingActionStatus,
    WarmingJobStatus,
)


class WarmingPlanConfigIn(BaseModel):
    """Optional overrides for the planner config used at job creation time."""

    duration_days: int | None = Field(default=None, ge=1, le=30)
    actions_per_day_min: int | None = Field(default=None, ge=1, le=20)
    actions_per_day_max: int | None = Field(default=None, ge=1, le=50)
    target_trust_score: int | None = Field(default=None, ge=0, le=100)
    channels: list[str] | None = None
    reaction_targets: list[str] | None = None
    idle_chat_targets: list[str] | None = None


class WarmingJobCreateIn(BaseModel):
    account_id: int
    note: str | None = None
    plan: WarmingPlanConfigIn | None = None
    seed: int | None = Field(
        default=None,
        description="If provided, the planner uses a seeded RNG (reproducible plan).",
    )


class WarmingActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    kind: WarmingActionKind
    target: str | None
    scheduled_at: datetime
    executed_at: datetime | None
    status: WarmingActionStatus
    error: str | None
    trust_delta: int


class WarmingJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    account_id: int
    status: WarmingJobStatus
    target_trust_score: int
    started_at: datetime | None
    completed_at: datetime | None
    last_action_at: datetime | None
    note: str | None
    total_actions: int
    actions_done: int
    actions_failed: int
    actions_pending: int


class WarmingJobDetailOut(WarmingJobOut):
    actions: list[WarmingActionOut]


class WarmingActionCompleteIn(BaseModel):
    success: bool = True
    error: str | None = None


__all__ = [
    "WarmingActionCompleteIn",
    "WarmingActionOut",
    "WarmingJobCreateIn",
    "WarmingJobDetailOut",
    "WarmingJobOut",
    "WarmingPlanConfigIn",
]

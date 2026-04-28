"""Lifecycle stages and risk levels.

Stored as **plain strings** in the DB (`clients.current_stage`,
`clients.risk_level`) rather than SQLAlchemy `Enum` columns — SQLite +
Alembic + Enum migrations are awkward, and the only place these values
need to be validated is at the application boundary, where these enums
live.

Stage transitions and the rules around them are owned by `JourneyEngine`
(Layer 3). This file only defines the alphabet.
"""

from __future__ import annotations

from enum import StrEnum


class Stage(StrEnum):
    """Where in the relationship the fan currently is.

    Transitions are decided by `JourneyEngine.classify_stage` (Layer 3).
    """

    WELCOME = "welcome"
    """First contact. Sonya introduces herself, no PPV."""

    WARMUP = "warmup"
    """Small-talk / personal questions / building rapport."""

    QUALIFY = "qualify"
    """Fan engaged enough to gauge preferences / fan-type confidence."""

    OFFER_PENDING = "offer_pending"
    """An offer has been sent, awaiting decision."""

    AFTERCARE = "aftercare"
    """Fan just purchased — thank-you / check-in window."""

    REPEAT_READY = "repeat_ready"
    """Past purchaser, cooldown elapsed, eligible for next offer."""

    GHOST = "ghost"
    """No reply for N days (configurable). Eligible for ghost-recovery."""

    PAUSED_SAFETY = "paused_safety"
    """SafetyEngine raised a hard-stop; suppression active."""

    HANDOFF = "handoff"
    """Operator (or SafetyEngine) handed this conversation to a human."""


class RiskLevel(StrEnum):
    """Aggregate risk signal from SafetyEngine + history.

    `none` is the default for a fresh client. Higher values gate or block
    sales / proactive cadence (CadenceEngine in Layer 3).
    """

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Frozen tuples for runtime validation (avoids `enum` type-checking
# overhead and lets us accept raw strings from the DB without coercing).
STAGE_VALUES: tuple[str, ...] = tuple(s.value for s in Stage)
RISK_LEVEL_VALUES: tuple[str, ...] = tuple(r.value for r in RiskLevel)


def is_valid_stage(value: str) -> bool:
    return value in STAGE_VALUES


def is_valid_risk_level(value: str) -> bool:
    return value in RISK_LEVEL_VALUES

"""Immutable dataclass models for the Sonya template library.

Backed 1:1 by `data/template_library.json`. We keep the JSON as the source
of truth (versioned, reviewable in PRs) and parse it into frozen dataclasses
at import time so consumers get static-typed access without a runtime
dependency on Pydantic / SQLAlchemy.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MetaRule:
    """One of MR1..MR10 — a global behavioural rule for the persona."""

    id: str
    rule: str


@dataclass(frozen=True, slots=True)
class StopLists:
    """Forbidden vocabulary, emojis, and structural patterns."""

    forbidden_words: dict[str, tuple[str, ...]] = field(default_factory=dict)
    forbidden_emojis: tuple[str, ...] = ()
    forbidden_emoji_patterns: tuple[str, ...] = ()
    allowed_emojis_default_zero: tuple[str, ...] = ()
    allowed_emoji_rules: tuple[str, ...] = ()
    forbidden_structures: tuple[str, ...] = ()
    approved_starter_phrases_by_grain: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PresendCheck:
    """One item in the 9-item pre-send self-check."""

    check: int
    question: str


@dataclass(frozen=True, slots=True)
class Grain:
    """Voice / tone bucket. 12 of them (G1..G12)."""

    id: str
    name: str
    when: str
    tone: str
    markers: tuple[str, ...]
    starter_phrases: tuple[str, ...]
    anti_patterns: tuple[str, ...]
    examples_good: tuple[str, ...]
    examples_bad: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Archetype:
    """Fan archetype (A1..A37) — funnel-stage / behaviour cluster."""

    id: str
    name: str
    category: str
    definition: str
    primary_grain: str | None
    secondary_grain: str | None
    signature: str
    detection_signals: tuple[str, ...]
    default_rail: str
    default_overlay: str | None
    rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StageTransition:
    """Edge from one rail stage to another, gated by an event."""

    event: str
    next: str
    flag: str | None = None
    overlay_add: str | None = None
    rule: str | None = None


@dataclass(frozen=True, slots=True)
class StageTimer:
    """Timer firing within a rail stage."""

    after_h: float
    action: str
    template_ref: str | None = None


@dataclass(frozen=True, slots=True)
class Stage:
    """One node on the master rail (S0..Sn)."""

    id: str
    description: str
    bot_action: str
    default_grain: str | None
    transitions: tuple[StageTransition, ...] = ()
    timers: tuple[StageTimer, ...] = ()
    template_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Template:
    """Few-shot template: a `good` example + a `bad` foil with reasons."""

    id: str
    situation: str
    stage: str
    fan_types: tuple[str, ...]
    grain: str
    tempo: str
    good: str
    bad: str
    why_good: str
    why_bad: str
    violations_in_bad: tuple[str, ...]
    source: str


@dataclass(frozen=True, slots=True)
class ActiveWindow:
    """Time-of-day windows mapping grains to local hours."""

    windows_for_grain: dict[str, tuple[int, int]] = field(default_factory=dict)


__all__ = [
    "ActiveWindow",
    "Archetype",
    "Grain",
    "MetaRule",
    "PresendCheck",
    "Stage",
    "StageTimer",
    "StageTransition",
    "StopLists",
    "Template",
]

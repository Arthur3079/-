"""Unit tests for `sonya.combine.warming.planner.WarmingPlanner`."""

from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from sonya.combine.warming.planner import (
    DEFAULT_PLAN_CONFIG,
    PlanConfig,
    WarmingPlanner,
    estimate_total_trust,
)
from sonya.db.models_combine import (
    Account,
    AccountRole,
    AccountStatus,
    WarmingActionKind,
    WarmingActionStatus,
)


def _account() -> Account:
    acc = Account()
    acc.id = 1
    acc.owner_id = 1
    acc.phone = "+10000000000"
    acc.role = AccountRole.MULTI
    acc.status = AccountStatus.NEW
    return acc


def test_plan_uses_full_window_and_orders_by_time() -> None:
    planner = WarmingPlanner(rng=random.Random(42))
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    actions = planner.build(_account(), started_at=start, config=DEFAULT_PLAN_CONFIG)

    assert actions, "planner produced no actions"
    # All scheduled in [start, start + duration_days+1)
    end_inclusive = start.replace(day=start.day) + (
        DEFAULT_PLAN_CONFIG.duration_days * (actions[0].scheduled_at - actions[0].scheduled_at)
        if False
        else __import__("datetime").timedelta(days=DEFAULT_PLAN_CONFIG.duration_days)
    )
    for a in actions:
        assert start <= a.scheduled_at <= end_inclusive
        assert a.status == WarmingActionStatus.PENDING
    # Sorted by scheduled_at.
    assert actions == sorted(actions, key=lambda a: a.scheduled_at)


def test_plan_is_reproducible_with_seed() -> None:
    cfg = PlanConfig(duration_days=3)
    a = WarmingPlanner(random.Random(7)).build(_account(), config=cfg)
    b = WarmingPlanner(random.Random(7)).build(_account(), config=cfg)
    kinds_a = [(x.kind, x.target) for x in a]
    kinds_b = [(x.kind, x.target) for x in b]
    assert kinds_a == kinds_b


def test_plan_rejects_bad_config() -> None:
    bad = PlanConfig(duration_days=0)
    with pytest.raises(ValueError):
        WarmingPlanner().build(_account(), config=bad)

    bad2 = PlanConfig(actions_per_day_min=5, actions_per_day_max=2)
    with pytest.raises(ValueError):
        WarmingPlanner().build(_account(), config=bad2)


def test_plan_progressive_risk_curve() -> None:
    """Day 0 should never schedule reactions or idle DMs."""
    cfg = PlanConfig(
        duration_days=7,
        actions_per_day_min=20,
        actions_per_day_max=20,
        idle_chat_targets=("alice",),
    )
    planner = WarmingPlanner(rng=random.Random(0))
    actions = planner.build(_account(), config=cfg)

    # Group by day.
    from collections import defaultdict

    per_day: dict[int, list[WarmingActionKind]] = defaultdict(list)
    start = actions[0].scheduled_at.replace(hour=0, minute=0, second=0, microsecond=0)
    for a in actions:
        day = (a.scheduled_at - start).days
        per_day[day].append(a.kind)

    # Day 0 must be subscribe / read only.
    assert WarmingActionKind.REACT_POST not in per_day[0]
    assert WarmingActionKind.SEND_IDLE_MESSAGE not in per_day[0]


def test_plan_idle_messages_only_when_targets_configured() -> None:
    cfg = PlanConfig(duration_days=7, idle_chat_targets=())
    actions = WarmingPlanner(random.Random(1)).build(_account(), config=cfg)
    # No idle target list ⇒ even when planner picks SEND_IDLE_MESSAGE,
    # target is None (operator-clean).
    for a in actions:
        if a.kind == WarmingActionKind.SEND_IDLE_MESSAGE:
            assert a.target is None


def test_estimate_total_trust_helper() -> None:
    cfg = PlanConfig(
        duration_days=2,
        actions_per_day_min=4,
        actions_per_day_max=4,
        trust_per_subscribe=2,
        trust_per_read=1,
        trust_per_react=3,
        trust_per_idle_msg=4,
    )
    actions = WarmingPlanner(random.Random(0)).build(_account(), config=cfg)
    total = estimate_total_trust(actions)
    # 8 actions × min delta 1 ≤ total ≤ 8 × max delta 4.
    assert 8 <= total <= 32

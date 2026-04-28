"""Generate a warm-up plan for a single account.

The planner is **deterministic** w.r.t. its `random.Random` instance — pass
a seeded RNG in tests so the schedule is reproducible.

The default plan, for a fresh account:

* Days 1-3:  subscribe to a handful of channels, then read history (low risk).
* Days 4-5:  start setting reactions on posts.
* Days 6-7:  send a few idle DMs to peers (highest risk — goes last).

Every step has a small ``trust_delta`` (typically 1-3) and the sum is roughly
calibrated so finishing the whole plan brings ``trust_score`` close to
``target_trust_score`` (default 50).
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sonya.db.models_combine import (
    Account,
    WarmingAction,
    WarmingActionKind,
    WarmingActionStatus,
)


@dataclass(frozen=True)
class PlanConfig:
    """Knobs for plan generation. All durations are in seconds-precision."""

    duration_days: int = 7
    """Calendar window over which actions are distributed."""

    actions_per_day_min: int = 3
    actions_per_day_max: int = 8

    channels: Sequence[str] = field(
        default_factory=lambda: (
            "telegram",
            "durov",
            "tginfo",
            "tdesktop",
            "BotNews",
        )
    )
    """Default safe public channels to subscribe / read."""

    reaction_targets: Sequence[str] = field(default_factory=lambda: ("telegram", "durov", "tginfo"))
    """Channels where the warmer can leave reactions."""

    idle_chat_targets: Sequence[str] = field(default_factory=tuple)
    """Peer usernames to send idle DMs to. Empty by default — operator
    must opt in (DMs to strangers carry the highest spam-block risk)."""

    trust_per_subscribe: int = 2
    trust_per_read: int = 1
    trust_per_react: int = 3
    trust_per_idle_msg: int = 4

    target_trust_score: int = 50


DEFAULT_PLAN_CONFIG = PlanConfig()


class WarmingPlanner:
    """Stateless service that produces an ordered list of warming actions.

    Usage::

        planner = WarmingPlanner(rng=random.Random(42))
        actions = planner.build(account, started_at=now, config=PlanConfig())
        for a in actions:
            session.add(a)

    The returned :class:`WarmingAction` rows are NOT attached to a job —
    the caller (`/api/combine/warming/jobs` POST handler) wires them up.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    def build(
        self,
        account: Account,
        *,
        started_at: datetime | None = None,
        config: PlanConfig = DEFAULT_PLAN_CONFIG,
    ) -> list[WarmingAction]:
        del account  # reserved for future per-account customisation
        if config.duration_days < 1:
            raise ValueError("duration_days must be >= 1")
        if config.actions_per_day_min < 1:
            raise ValueError("actions_per_day_min must be >= 1")
        if config.actions_per_day_max < config.actions_per_day_min:
            raise ValueError("actions_per_day_max must be >= actions_per_day_min")

        start = (started_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        actions: list[WarmingAction] = []

        for day in range(config.duration_days):
            day_actions = self._plan_day(
                day=day, config=config, day_start=start + timedelta(days=day)
            )
            actions.extend(day_actions)

        # Sort once at the end so the list is monotonically increasing in time.
        actions.sort(key=lambda a: a.scheduled_at)
        return actions

    def _plan_day(
        self,
        *,
        day: int,
        config: PlanConfig,
        day_start: datetime,
    ) -> list[WarmingAction]:
        n_actions = self._rng.randint(config.actions_per_day_min, config.actions_per_day_max)
        kinds = _choose_kinds_for_day(
            day=day, total_days=config.duration_days, n=n_actions, rng=self._rng
        )
        actions: list[WarmingAction] = []
        for kind in kinds:
            offset_seconds = self._rng.randint(8 * 3600, 22 * 3600)
            scheduled_at = day_start + timedelta(seconds=offset_seconds)
            actions.append(
                WarmingAction(
                    kind=kind,
                    target=self._target_for(kind, config),
                    scheduled_at=scheduled_at,
                    status=WarmingActionStatus.PENDING,
                    trust_delta=self._delta_for(kind, config),
                )
            )
        return actions

    def _target_for(self, kind: WarmingActionKind, config: PlanConfig) -> str | None:
        if kind == WarmingActionKind.SUBSCRIBE_CHANNEL:
            pool = config.channels
        elif kind == WarmingActionKind.READ_HISTORY:
            pool = config.channels
        elif kind == WarmingActionKind.REACT_POST:
            pool = config.reaction_targets
        elif kind == WarmingActionKind.SEND_IDLE_MESSAGE:
            pool = config.idle_chat_targets
        else:  # pragma: no cover - defensive
            return None
        if not pool:
            return None
        return self._rng.choice(list(pool))

    @staticmethod
    def _delta_for(kind: WarmingActionKind, config: PlanConfig) -> int:
        return {
            WarmingActionKind.SUBSCRIBE_CHANNEL: config.trust_per_subscribe,
            WarmingActionKind.READ_HISTORY: config.trust_per_read,
            WarmingActionKind.REACT_POST: config.trust_per_react,
            WarmingActionKind.SEND_IDLE_MESSAGE: config.trust_per_idle_msg,
        }[kind]


def _choose_kinds_for_day(
    *, day: int, total_days: int, n: int, rng: random.Random
) -> list[WarmingActionKind]:
    """Weighted random pick — riskier actions become available later in the plan."""

    # Phase 0: subscribe + read.   Phase 1: + react.   Phase 2: + idle DMs.
    progress = day / max(total_days - 1, 1)

    weights: dict[WarmingActionKind, float]
    if progress < 0.4:
        weights = {
            WarmingActionKind.SUBSCRIBE_CHANNEL: 0.4,
            WarmingActionKind.READ_HISTORY: 0.6,
            WarmingActionKind.REACT_POST: 0.0,
            WarmingActionKind.SEND_IDLE_MESSAGE: 0.0,
        }
    elif progress < 0.75:
        weights = {
            WarmingActionKind.SUBSCRIBE_CHANNEL: 0.15,
            WarmingActionKind.READ_HISTORY: 0.45,
            WarmingActionKind.REACT_POST: 0.4,
            WarmingActionKind.SEND_IDLE_MESSAGE: 0.0,
        }
    else:
        weights = {
            WarmingActionKind.SUBSCRIBE_CHANNEL: 0.05,
            WarmingActionKind.READ_HISTORY: 0.30,
            WarmingActionKind.REACT_POST: 0.45,
            WarmingActionKind.SEND_IDLE_MESSAGE: 0.20,
        }

    kinds: list[WarmingActionKind] = []
    pool = list(weights.keys())
    pool_weights = [weights[k] for k in pool]
    for _ in range(n):
        kinds.append(rng.choices(pool, weights=pool_weights, k=1)[0])
    return kinds


def estimate_total_trust(actions: Iterable[WarmingAction]) -> int:
    """Sum of ``trust_delta`` across pending+done actions — used by tests."""
    return sum(a.trust_delta for a in actions)


__all__ = [
    "DEFAULT_PLAN_CONFIG",
    "PlanConfig",
    "WarmingPlanner",
    "estimate_total_trust",
]

"""Account warming module — schedules low-risk activity on fresh accounts.

Public surface:

* :class:`WarmingPlanner` — produces a list of :class:`WarmingAction` rows
  spread out over time, given a config and a target account.
* :class:`TrustScoreUpdater` — bumps :attr:`Account.trust_score` when an
  action completes successfully.
* :mod:`repository` — async DB helpers for jobs/actions.
* :mod:`schemas` — Pydantic request/response models.
"""

from sonya.combine.warming.planner import (
    DEFAULT_PLAN_CONFIG,
    PlanConfig,
    WarmingPlanner,
)
from sonya.combine.warming.telethon_executor import TelethonWarmingExecutor
from sonya.combine.warming.trust import TrustScoreUpdater
from sonya.combine.warming.worker_plugin import WarmingWorkerPlugin

__all__ = [
    "DEFAULT_PLAN_CONFIG",
    "PlanConfig",
    "TelethonWarmingExecutor",
    "TrustScoreUpdater",
    "WarmingPlanner",
    "WarmingWorkerPlugin",
]

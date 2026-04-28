"""Journey package: lifecycle stages, risk levels, and (in later layers)
the deterministic state-machine + next-best-action engines.

Layer 1 only ships the **enums** and a minimal helper. The state machine,
NextBestActionEngine and CadenceEngine are added in Layer 3.
"""

from __future__ import annotations

from sonya.journey.stages import (
    RISK_LEVEL_VALUES,
    STAGE_VALUES,
    RiskLevel,
    Stage,
    is_valid_risk_level,
    is_valid_stage,
)

# `next_best_action` is intentionally NOT re-exported here: it depends on
# `sonya.safety`, which depends on `sonya.crm.repository`, which depends
# on `sonya.journey` — eager-importing it would form a cycle. Callers
# import directly: `from sonya.journey.next_best_action import ...`.

__all__ = [
    "RISK_LEVEL_VALUES",
    "RiskLevel",
    "STAGE_VALUES",
    "Stage",
    "is_valid_risk_level",
    "is_valid_stage",
]

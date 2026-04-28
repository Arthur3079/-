"""Combine module 6 — mass reactions.

Distributes reactions from a configured emoji set across a pool of
accounts under each target post (a campaign). The actual posting is
done by an external worker (Sprint 7); this module ships only the
bookkeeping side and a deterministic planner.
"""

from sonya.combine.reactions.planner import (
    PlannedReaction,
    ReactionPlanner,
)

__all__ = ["PlannedReaction", "ReactionPlanner"]

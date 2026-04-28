"""Decide who reacts with what under a target post.

Deterministic so callers can re-run the planner against the same
``ReactionTarget`` and re-produce the exact same plan (useful for
idempotent worker handlers and reproducible tests).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from sonya.db.models_combine import (
    ReactionCampaign,
    ReactionTarget,
)


@dataclass(frozen=True)
class PlannedReaction:
    """One (account, emoji) pair the planner has chosen for a target."""

    account_id: int
    emoji: str


class ReactionPlanner:
    """Pick `accounts_per_post` accounts and assign each one an emoji.

    The planner is deterministic given a (campaign, target) pair: the
    seed is derived from the target's primary key, so re-planning the
    same target always returns the same assignment.

    Rules:

    * Account pool size must be ``>= accounts_per_post`` — otherwise the
      planner returns at most ``len(account_ids)`` plans (no filling).
    * Emoji pool must be non-empty.
    * Each account gets exactly one emoji per call.
    * Emojis are sampled with replacement (the same emoji may appear
      twice across accounts under the same target — that's fine: it's
      what real channels look like).
    """

    def __init__(self, *, seed_salt: int = 0) -> None:
        self._seed_salt = seed_salt

    def plan(self, *, campaign: ReactionCampaign, target: ReactionTarget) -> list[PlannedReaction]:
        if not campaign.emojis:
            raise ValueError("campaign has no emojis configured")
        if campaign.accounts_per_post < 1:
            raise ValueError("accounts_per_post must be >= 1")

        pool = list(dict.fromkeys(campaign.account_ids))  # de-dupe, preserve order
        if not pool:
            return []

        seed = (target.id or 0) ^ self._seed_salt ^ (campaign.id or 0)
        rng = random.Random(seed)

        take = min(campaign.accounts_per_post, len(pool))
        chosen = rng.sample(pool, take)
        emojis = list(campaign.emojis)
        return [PlannedReaction(account_id=acc, emoji=rng.choice(emojis)) for acc in chosen]


__all__ = ["PlannedReaction", "ReactionPlanner"]

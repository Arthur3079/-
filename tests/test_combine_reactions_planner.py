"""Unit tests for `ReactionPlanner`."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sonya.combine.reactions.planner import ReactionPlanner
from sonya.db.models_combine import (
    ReactionCampaign,
    ReactionCampaignStatus,
    ReactionTarget,
    ReactionTargetStatus,
)


def _campaign(
    *,
    accounts: list[int],
    emojis: list[str],
    accounts_per_post: int = 3,
    cid: int = 1,
) -> ReactionCampaign:
    c = ReactionCampaign()
    c.id = cid
    c.owner_id = 1
    c.name = "test"
    c.target_channels = []
    c.account_ids = accounts
    c.emojis = emojis
    c.accounts_per_post = accounts_per_post
    c.max_reactions_per_day = 200
    c.status = ReactionCampaignStatus.DRAFT
    return c


def _target(tid: int = 1, campaign_id: int = 1) -> ReactionTarget:
    t = ReactionTarget()
    t.id = tid
    t.campaign_id = campaign_id
    t.channel = "@news"
    t.tg_message_id = 42
    t.status = ReactionTargetStatus.PENDING
    t.observed_at = datetime.now(timezone.utc)
    return t


def test_plan_picks_correct_count() -> None:
    plans = ReactionPlanner().plan(
        campaign=_campaign(accounts=[1, 2, 3, 4, 5], emojis=["👍"], accounts_per_post=3),
        target=_target(),
    )
    assert len(plans) == 3
    assert {p.account_id for p in plans} <= {1, 2, 3, 4, 5}
    assert all(p.emoji == "👍" for p in plans)


def test_plan_unique_accounts_within_one_target() -> None:
    plans = ReactionPlanner().plan(
        campaign=_campaign(accounts=[1, 2, 3, 4, 5], emojis=["👍", "🔥", "❤️"], accounts_per_post=4),
        target=_target(),
    )
    account_ids = [p.account_id for p in plans]
    assert len(account_ids) == 4
    assert len(set(account_ids)) == 4  # no duplicates


def test_plan_is_deterministic_for_same_target() -> None:
    campaign = _campaign(
        accounts=[1, 2, 3, 4, 5, 6, 7, 8],
        emojis=["👍", "🔥", "❤️", "👏"],
        accounts_per_post=3,
    )
    p1 = ReactionPlanner().plan(campaign=campaign, target=_target(tid=42))
    p2 = ReactionPlanner().plan(campaign=campaign, target=_target(tid=42))
    assert p1 == p2


def test_plan_differs_across_targets() -> None:
    campaign = _campaign(
        accounts=list(range(1, 21)),
        emojis=["👍", "🔥", "❤️", "👏", "🚀"],
        accounts_per_post=3,
    )
    p_a = ReactionPlanner().plan(campaign=campaign, target=_target(tid=1))
    p_b = ReactionPlanner().plan(campaign=campaign, target=_target(tid=2))
    # Extremely unlikely to be identical with this many accounts/emojis.
    assert p_a != p_b


def test_plan_caps_count_to_pool_size() -> None:
    plans = ReactionPlanner().plan(
        campaign=_campaign(accounts=[1, 2], emojis=["👍"], accounts_per_post=10),
        target=_target(),
    )
    assert len(plans) == 2


def test_plan_empty_pool_returns_empty() -> None:
    plans = ReactionPlanner().plan(
        campaign=_campaign(accounts=[], emojis=["👍"]),
        target=_target(),
    )
    assert plans == []


def test_plan_dedupes_account_pool() -> None:
    plans = ReactionPlanner().plan(
        campaign=_campaign(accounts=[1, 1, 2, 2, 3, 3], emojis=["👍"], accounts_per_post=3),
        target=_target(),
    )
    assert {p.account_id for p in plans} == {1, 2, 3}


def test_plan_no_emojis_raises() -> None:
    with pytest.raises(ValueError):
        ReactionPlanner().plan(
            campaign=_campaign(accounts=[1, 2], emojis=[]),
            target=_target(),
        )


def test_plan_invalid_accounts_per_post_raises() -> None:
    with pytest.raises(ValueError):
        ReactionPlanner().plan(
            campaign=_campaign(accounts=[1], emojis=["👍"], accounts_per_post=0),
            target=_target(),
        )

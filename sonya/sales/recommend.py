"""Pick a `ContentSet` for one fan based on their type / current intent.

The selection is deliberately simple and deterministic so it's easy to
reason about: if the catalog has a set whose `target_types` mentions the
fan's coarse class (or fine A1..G3 label), and the fan hasn't bought it
already, prefer it. Lower-priced sets win for newcomers; whales get
higher-priced ones first.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.crm.classifier import FanTypeLite as FanType
from sonya.db.models import ContentDelivery, ContentSet


async def recommend_for_fan(
    session: AsyncSession,
    *,
    fan_id: int,
    fan_type_lite: str | None = None,
    fan_type_fine: str | None = None,
    limit: int = 3,
) -> list[ContentSet]:
    """Return up to `limit` candidate sets, best-first.

    `fan_type_lite` is one of `FanType` values (NEWCOMER/REGULAR/...).
    `fan_type_fine` is the optional fine-grained A1..G3 label from manual ops.
    """
    delivered_q = await session.execute(
        select(ContentDelivery.content_set_id).where(ContentDelivery.fan_id == fan_id)
    )
    already: set[int] = {r[0] for r in delivered_q.all() if r[0] is not None}

    res = await session.execute(select(ContentSet).where(ContentSet.is_active.is_(True)))
    all_sets: list[ContentSet] = list(res.scalars().all())
    if not all_sets:
        return []

    candidates: list[tuple[int, ContentSet]] = []
    for cs in all_sets:
        if cs.id in already:
            continue
        score = _score(cs, fan_type_lite=fan_type_lite, fan_type_fine=fan_type_fine)
        if score < 0:
            continue
        candidates.append((score, cs))

    candidates.sort(key=lambda x: (-x[0], x[1].price_stars or 0))
    return [cs for _, cs in candidates[:limit]]


def _score(
    cs: ContentSet,
    *,
    fan_type_lite: str | None,
    fan_type_fine: str | None,
) -> int:
    """Higher = better fit. -1 = explicitly not for this fan."""
    targets = (cs.target_types or "").upper()
    score = 0
    if fan_type_fine and fan_type_fine.upper() in targets:
        score += 10
    lite = (fan_type_lite or "").lower()
    if lite:
        # Map lite types to coarse catalog tags. WHALE → B1; NEWCOMER → A1.
        mapping = {
            FanType.WHALE.value: "B1",
            FanType.NEWCOMER.value: "A1",
            FanType.REGULAR.value: "A5",
            FanType.GHOST.value: "A6",
            FanType.RISKY.value: "C7",
        }
        proxy = mapping.get(lite)
        if proxy and proxy in targets:
            score += 5
        if lite == FanType.WHALE.value:
            # Whales like premium (Tier 2/3, higher prices).
            score += min(int((cs.price_usd_equivalent or 0) // 10), 5)
        if lite == FanType.NEWCOMER.value:
            # Newcomers: cheaper sets first.
            if cs.price_usd_equivalent and cs.price_usd_equivalent <= 20:
                score += 3
        if lite == FanType.RISKY.value:
            # Don't push content on risky fans.
            return -1
    if not cs.target_types:
        score += 1  # generic set; weak default match
    return score

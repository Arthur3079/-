"""Parse `knowledge/content_catalog.md` into rows of `content_sets`.

The catalog is curated markdown shaped like:

    ## 01. Disco_ball_white_panties_studio
    **Кадров:** ~12 | **Цвет:** бирюзовый

    - **Vibe:** ...
    - **Preview без 18+:** ...
    - **Tier:** Tier 2 mid PPV — **$22-28**.
    - **Грань Сони:** G3 + G6.
    - **Подходит типам:** C2 playful flirt, C4 status spender, B1 whale, F2 ...
    - **Не предлагать:** C1 shy, ...
    - **PPV-копи:** ...
    - **Feed-стратегия:** ...

Implementation goals:

- Pure parser: input str → list[CatalogEntry], no DB.
- Idempotent upsert keyed by `code` ("01", "02", ...). Re-running the import
  updates name / target_types / theme without creating duplicates.
- Tolerant: missing fields are accepted, unknown lines are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import ContentSet

_HEADER = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.MULTILINE)
_PRICE = re.compile(r"\$([0-9]+)\s*(?:[-–]\s*([0-9]+))?")
_TARGET = re.compile(r"\*\*Подходит типам:\*\*\s*(.+)")
_BLOCK = re.compile(r"\*\*Не предлагать:\*\*\s*(.+)")
_TIER = re.compile(r"\*\*Tier:\*\*\s*(.+)")
_THEME = re.compile(r"\*\*Цвет:\*\*\s*([^\n|]+)")
_VIBE = re.compile(r"\*\*Vibe:\*\*\s*(.+)")

# Telegram Stars rough conversion: ~$0.013/star at the time of writing. We
# only use this as a *display fallback* — operators tune the real price.
_USD_TO_STARS = 75


@dataclass
class CatalogEntry:
    code: str
    name: str
    theme: str | None = None
    price_usd_low: float | None = None
    price_usd_high: float | None = None
    price_stars: int = 0
    description: str | None = None
    target_types: list[str] = field(default_factory=list)
    blocked_types: list[str] = field(default_factory=list)

    @property
    def price_usd_equivalent(self) -> float:
        if self.price_usd_low is None and self.price_usd_high is None:
            return 0.0
        if self.price_usd_low is None:
            return float(self.price_usd_high)
        if self.price_usd_high is None:
            return float(self.price_usd_low)
        return (self.price_usd_low + self.price_usd_high) / 2.0


def parse_catalog(text: str) -> list[CatalogEntry]:
    """Split markdown into per-set blocks and parse each one."""
    matches = list(_HEADER.finditer(text))
    if not matches:
        return []
    entries: list[CatalogEntry] = []
    for i, m in enumerate(matches):
        code = m.group(1)
        name = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        entries.append(_parse_block(code=code, name=name, body=body))
    return entries


def _parse_block(*, code: str, name: str, body: str) -> CatalogEntry:
    entry = CatalogEntry(code=code, name=name)

    theme_m = _THEME.search(body)
    if theme_m:
        entry.theme = theme_m.group(1).strip()

    tier_m = _TIER.search(body)
    if tier_m:
        price_m = _PRICE.search(tier_m.group(1))
        if price_m:
            entry.price_usd_low = float(price_m.group(1))
            if price_m.group(2):
                entry.price_usd_high = float(price_m.group(2))

    target_m = _TARGET.search(body)
    if target_m:
        entry.target_types = _split_csv(target_m.group(1))

    block_m = _BLOCK.search(body)
    if block_m:
        entry.blocked_types = _split_csv(block_m.group(1))

    vibe_m = _VIBE.search(body)
    desc_parts: list[str] = []
    if vibe_m:
        desc_parts.append(f"Vibe: {vibe_m.group(1).strip()}")
    if entry.theme:
        desc_parts.append(f"Theme: {entry.theme}")
    if entry.target_types:
        desc_parts.append(f"Target: {', '.join(entry.target_types)}")
    entry.description = " | ".join(desc_parts) or None

    entry.price_stars = (
        int(round(entry.price_usd_equivalent * _USD_TO_STARS)) if entry.price_usd_equivalent else 0
    )
    return entry


def _split_csv(s: str) -> list[str]:
    """Pull short type-code tokens (A1, C2, F4 etc.) out of a free-form line."""
    cleaned = re.split(r"[,;]", s)
    out: list[str] = []
    for piece in cleaned:
        # Take only the leading code if it's "C2 playful flirt"
        m = re.match(r"\s*([A-Z]\d{1,2})\b", piece)
        if m:
            out.append(m.group(1))
            continue
        token = piece.strip()
        if token:
            out.append(token)
    # de-dupe preserving order
    seen: set[str] = set()
    return [t for t in out if not (t in seen or seen.add(t))]


async def upsert_entry(session: AsyncSession, *, entry: CatalogEntry) -> ContentSet:
    res = await session.execute(select(ContentSet).where(ContentSet.code == entry.code))
    row = res.scalar_one_or_none()
    target_csv = ",".join(entry.target_types) or None
    if row is None:
        row = ContentSet(
            code=entry.code,
            name=entry.name,
            theme=entry.theme,
            price_stars=entry.price_stars,
            price_usd_equivalent=entry.price_usd_equivalent,
            description=entry.description,
            target_types=target_csv,
            is_active=True,
        )
        session.add(row)
    else:
        row.name = entry.name
        row.theme = entry.theme
        row.price_stars = entry.price_stars
        row.price_usd_equivalent = entry.price_usd_equivalent
        row.description = entry.description
        row.target_types = target_csv
    await session.flush()
    return row


async def import_catalog_file(session: AsyncSession, *, path: Path) -> int:
    """Parse a markdown file and upsert every entry. Returns rows touched."""
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8")
    entries = parse_catalog(text)
    for entry in entries:
        await upsert_entry(session, entry=entry)
    return len(entries)

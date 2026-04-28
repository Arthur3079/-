"""Split an LLM reply into 1–N short bubbles for more human-feeling sends.

Real people often send "hey 💛" first and the substantive answer second
instead of one paragraph. This helper turns one LLM string into ≤N strings.

Strategy:
1. If the reply is short enough, return it as a single bubble (no split).
2. Otherwise, prefer paragraph boundaries (`\\n\\n`).
3. If there's still nothing to split on (one big paragraph), fall back to
   sentence boundaries.
4. Greedily merge adjacent pieces back together until each bubble is ≥
   `min_chars` (avoids ridiculous "ok." / "yeah." standalone bubbles).
5. Cap at `max_bubbles`; the tail is concatenated into the final bubble.

The function is pure & synchronous — easy to unit-test.
"""

from __future__ import annotations

import re

DEFAULT_MAX_BUBBLES = 3
DEFAULT_SINGLE_CHARS = 180  # ≤ this and we don't bother splitting
DEFAULT_MIN_CHARS = 60  # avoid micro-bubbles


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def split_into_bubbles(
    text: str,
    *,
    max_bubbles: int = DEFAULT_MAX_BUBBLES,
    single_threshold: int = DEFAULT_SINGLE_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> list[str]:
    """Return 1..`max_bubbles` non-empty trimmed strings."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= single_threshold:
        return [cleaned]
    if max_bubbles <= 1:
        return [cleaned]

    # 1. Paragraph split.
    parts = [p.strip() for p in re.split(r"\n{2,}", cleaned) if p.strip()]
    if len(parts) < 2:
        # 2. Sentence split.
        parts = [s.strip() for s in _SENTENCE_SPLIT.split(cleaned) if s.strip()]
        if len(parts) < 2:
            return [cleaned]

    # 3. Greedy merge so each bubble is at least `min_chars` long.
    merged: list[str] = []
    buf = ""
    for part in parts:
        if not buf:
            buf = part
            continue
        if len(buf) < min_chars:
            buf = f"{buf} {part}".strip()
        else:
            merged.append(buf)
            buf = part
    if buf:
        merged.append(buf)

    if len(merged) <= max_bubbles:
        return merged

    # 4. Cap: keep first (max_bubbles-1) intact, concat the rest.
    head = merged[: max_bubbles - 1]
    tail = " ".join(merged[max_bubbles - 1 :]).strip()
    return [*head, tail]

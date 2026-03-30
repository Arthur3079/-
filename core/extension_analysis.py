from __future__ import annotations

from collections import defaultdict
from pathlib import Path


def aggregate_extensions(paths_with_sizes: dict[Path, int]) -> dict[str, int]:
    """Агрегирует суммарный размер по расширению файла."""

    totals: dict[str, int] = defaultdict(int)
    for path, size in paths_with_sizes.items():
        ext = path.suffix.lower() or "[без расширения]"
        totals[ext] += max(size, 0)
    return dict(sorted(totals.items(), key=lambda item: item[1], reverse=True))

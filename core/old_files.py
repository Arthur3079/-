from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable


@dataclass(slots=True)
class OldFileInfo:
    path: Path
    size_bytes: int
    last_access: datetime
    months_unused: int


def find_old_files(
    root_path: str | Path,
    months: int = 6,
    *,
    cancel_check: Callable[[], bool] | None = None,
    progress_cb: Callable[[int], None] | None = None,
    current_path_cb: Callable[[str], None] | None = None,
) -> list[OldFileInfo]:
    root = Path(root_path)
    threshold = datetime.now() - timedelta(days=months * 30)
    found: list[OldFileInfo] = []

    scanned = 0
    for path in _iter_files(root):
        if cancel_check and cancel_check():
            break

        scanned += 1
        if current_path_cb:
            current_path_cb(str(path))
        if progress_cb and scanned % 200 == 0:
            progress_cb((scanned // 200) % 100)

        try:
            stat = path.stat()
        except OSError:
            continue

        last_access = datetime.fromtimestamp(stat.st_atime)
        if last_access > threshold:
            continue

        found.append(
            OldFileInfo(
                path=path,
                size_bytes=stat.st_size,
                last_access=last_access,
                months_unused=months,
            )
        )

    found.sort(key=lambda f: f.last_access)
    if progress_cb:
        progress_cb(100)
    return found


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return

    for path in root.rglob("*"):
        if path.is_file():
            yield path

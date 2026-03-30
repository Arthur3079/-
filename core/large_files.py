from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable


@dataclass(slots=True)
class LargeFileInfo:
    path: Path
    size_bytes: int
    last_access: datetime
    file_type: str


def _detect_file_type(path: Path) -> str:
    if path.suffix:
        return path.suffix.lower().lstrip(".")
    return "без расширения"


def find_large_files(
    root_path: str | Path,
    min_size_mb: int = 100,
    *,
    cancel_check: Callable[[], bool] | None = None,
    progress_cb: Callable[[int], None] | None = None,
    current_path_cb: Callable[[str], None] | None = None,
) -> list[LargeFileInfo]:
    """Ищет файлы, размер которых выше порога, и возвращает отсортированный список."""
    root = Path(root_path)
    min_size_bytes = int(min_size_mb * 1024 * 1024)

    found: list[LargeFileInfo] = []
    scanned = 0

    def should_cancel() -> bool:
        return cancel_check is not None and cancel_check()

    for file_path in _iter_files(root):
        if should_cancel():
            break

        scanned += 1
        if current_path_cb:
            current_path_cb(str(file_path))
        if progress_cb and scanned % 200 == 0:
            # Точный процент неизвестен без предварительного обхода,
            # поэтому передаём «пульсирующий» прогресс в диапазоне 0..99.
            progress_cb((scanned // 200) % 100)

        try:
            stat = file_path.stat()
        except OSError:
            continue

        if stat.st_size < min_size_bytes:
            continue

        found.append(
            LargeFileInfo(
                path=file_path,
                size_bytes=stat.st_size,
                last_access=datetime.fromtimestamp(stat.st_atime),
                file_type=_detect_file_type(file_path),
            )
        )

    found.sort(key=lambda item: item.size_bytes, reverse=True)
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

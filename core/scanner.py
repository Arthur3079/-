from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple


class ScanCancelled(Exception):
    """Raised when scan is cancelled by user."""


@dataclass(frozen=True)
class ScanProgress:
    current_folder: str
    percent: float


@dataclass(frozen=True)
class DirectorySize:
    path: str
    size: int


class DirectoryScanner:
    """
    Recursive directory scanner based on os.scandir() with:
    - directory size aggregation,
    - sorting by size,
    - cancellation support,
    - progress reporting,
    - in-memory cache.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, List[DirectorySize]] = {}
        self._lock = threading.Lock()

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def scan(
        self,
        root: str | os.PathLike[str],
        progress_cb: Optional[Callable[[ScanProgress], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        use_cache: bool = True,
    ) -> List[DirectorySize]:
        root_path = str(Path(root).resolve())

        if use_cache:
            with self._lock:
                cached = self._cache.get(root_path)
            if cached is not None:
                return list(cached)

        discovered_dirs = 1
        processed_dirs = 0
        dir_sizes: List[DirectorySize] = []

        def is_cancelled() -> bool:
            return bool(cancel_event and cancel_event.is_set())

        def emit_progress(current: str) -> None:
            if progress_cb is None:
                return
            percent = (processed_dirs / max(discovered_dirs, 1)) * 100.0
            progress_cb(ScanProgress(current_folder=current, percent=min(percent, 100.0)))

        def walk(path: Path) -> int:
            nonlocal discovered_dirs, processed_dirs

            if is_cancelled():
                raise ScanCancelled(f"Scan cancelled at: {path}")

            total_size = 0
            emit_progress(str(path))

            try:
                with os.scandir(path) as it:
                    for entry in it:
                        if is_cancelled():
                            raise ScanCancelled(f"Scan cancelled at: {path}")

                        try:
                            if entry.is_symlink():
                                continue

                            if entry.is_dir(follow_symlinks=False):
                                discovered_dirs += 1
                                total_size += walk(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                try:
                                    total_size += entry.stat(follow_symlinks=False).st_size
                                except OSError:
                                    continue
                        except (PermissionError, FileNotFoundError, OSError):
                            continue
            except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
                return 0

            processed_dirs += 1
            dir_sizes.append(DirectorySize(path=str(path), size=total_size))
            emit_progress(str(path))
            return total_size

        walk(Path(root_path))
        dir_sizes.sort(key=lambda item: item.size, reverse=True)

        with self._lock:
            self._cache[root_path] = list(dir_sizes)

        return dir_sizes

    def path_size(
        self,
        path: str | os.PathLike[str],
        cancel_event: Optional[threading.Event] = None,
    ) -> int:
        target = Path(path)
        if not target.exists():
            return 0

        if target.is_file():
            try:
                return target.stat().st_size
            except OSError:
                return 0

        total = 0
        try:
            with os.scandir(target) as it:
                for entry in it:
                    if cancel_event and cancel_event.is_set():
                        raise ScanCancelled(f"Size calculation cancelled at: {target}")
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            total += self.path_size(entry.path, cancel_event=cancel_event)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except (PermissionError, FileNotFoundError, OSError):
                        continue
        except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
            return 0
        return total

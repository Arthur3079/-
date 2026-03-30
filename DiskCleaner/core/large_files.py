"""Large files search."""

from pathlib import Path

from DiskCleaner.core.scanner import iter_files


def find_large_files(root: str, min_size_mb: int) -> list[Path]:
    threshold = min_size_mb * 1024 * 1024
    return [path for path in iter_files(root) if path.stat().st_size >= threshold]

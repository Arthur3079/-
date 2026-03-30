"""Old files search."""

from pathlib import Path

from DiskCleaner.core.scanner import iter_files
from DiskCleaner.core.utils import file_age_days


def find_old_files(root: str, min_age_days: int) -> list[Path]:
    return [path for path in iter_files(root) if file_age_days(path) >= min_age_days]

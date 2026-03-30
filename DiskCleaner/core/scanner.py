"""Generic filesystem scanner primitives."""

from pathlib import Path
from typing import Generator

from DiskCleaner.core.utils import can_access_path


def iter_files(root: str) -> Generator[Path, None, None]:
    """Yield files recursively from root while skipping inaccessible areas."""
    root_path = Path(root)
    if not can_access_path(root_path):
        return

    for path in root_path.rglob("*"):
        if path.is_file() and can_access_path(path):
            yield path

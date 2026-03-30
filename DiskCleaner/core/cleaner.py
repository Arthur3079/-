"""File cleanup helpers."""

from pathlib import Path


def delete_files(files: list[Path]) -> tuple[int, int]:
    """Delete files and return (deleted_count, failed_count)."""
    deleted = 0
    failed = 0
    for file_path in files:
        try:
            file_path.unlink(missing_ok=False)
            deleted += 1
        except OSError:
            failed += 1
    return deleted, failed

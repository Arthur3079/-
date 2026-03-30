"""Junk file discovery logic."""

from pathlib import Path

JUNK_PATTERNS = {"*.tmp", "*.log", "*.bak", "Thumbs.db", ".DS_Store"}


def find_junk(root: str) -> list[Path]:
    result: list[Path] = []
    root_path = Path(root)
    for pattern in JUNK_PATTERNS:
        result.extend(root_path.rglob(pattern))
    return result

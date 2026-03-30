"""Core utility functions for formatting, paths, dates, and access checks."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Optional


def format_size(num_bytes: int) -> str:
    """Format bytes into human-readable units."""
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(max(num_bytes, 0))
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{num_bytes} B"


def windows_safe_path(path: str | Path) -> str:
    """Return Windows long-path-safe form with \\?\\ prefix if needed."""
    raw = str(path)
    if os.name != "nt":
        return raw

    normalized = raw.replace("/", "\\")
    if normalized.startswith("\\\\?\\"):
        return normalized
    if normalized.startswith("\\\\"):
        # UNC path
        return "\\\\?\\UNC\\" + normalized.lstrip("\\")
    return "\\\\?\\" + normalized


def now_local() -> dt.datetime:
    """Return timezone-aware local current datetime."""
    return dt.datetime.now().astimezone()


def file_age_days(path: str | Path, reference: Optional[dt.datetime] = None) -> int:
    """Return file age in days based on modified timestamp."""
    reference = reference or now_local()
    modified = dt.datetime.fromtimestamp(Path(path).stat().st_mtime, tz=reference.tzinfo)
    return max((reference - modified).days, 0)


def datetime_to_str(value: dt.datetime) -> str:
    """Convert datetime to readable string."""
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def can_access_path(path: str | Path) -> bool:
    """Safely check read access to a file or folder."""
    candidate = Path(path)
    try:
        if not candidate.exists():
            return False
        if candidate.is_dir():
            next(candidate.iterdir(), None)
        else:
            with candidate.open("rb"):
                pass
        return True
    except (OSError, PermissionError, StopIteration):
        return False

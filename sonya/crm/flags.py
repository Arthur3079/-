"""Helpers for the csv-encoded `clients.flags` column.

Flags are a small, denormalized set of risk/state markers attached to a
client (e.g. `vulnerable_lite`, `off_platform`, `non_consent`,
`stop_request`). The data lives in `clients.flags` as a comma-separated
string for backwards compatibility with the existing schema.

These pure helpers operate on `str | None` and never touch the DB —
that's the responsibility of the repository.
"""

from __future__ import annotations

from collections.abc import Iterable


def parse_flags(raw: str | None) -> list[str]:
    """Return the flag list. Order preserved, duplicates dropped, empty
    strings dropped."""
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for piece in raw.split(","):
        f = piece.strip()
        if not f or f in seen:
            continue
        seen.add(f)
        out.append(f)
    return out


def serialize_flags(flags: Iterable[str]) -> str | None:
    """Inverse of `parse_flags`. Returns None for empty so the column can
    sit unset rather than as an empty string."""
    out: list[str] = []
    seen: set[str] = set()
    for f in flags:
        f = f.strip()
        if not f or f in seen:
            continue
        seen.add(f)
        out.append(f)
    return ",".join(out) if out else None


def has_flag(raw: str | None, flag: str) -> bool:
    return flag in parse_flags(raw)


def add_flag(raw: str | None, flag: str) -> str | None:
    flags = parse_flags(raw)
    if flag not in flags:
        flags.append(flag)
    return serialize_flags(flags)


def remove_flag(raw: str | None, flag: str) -> str | None:
    flags = [f for f in parse_flags(raw) if f != flag]
    return serialize_flags(flags)

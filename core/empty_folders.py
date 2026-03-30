from __future__ import annotations

from pathlib import Path


def find_empty_folders(root: Path, include_hidden: bool = False) -> list[Path]:
    """Ищет пустые папки как отдельный инструмент сканирования."""

    empty_dirs: list[Path] = []
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not include_hidden and directory.name.startswith("."):
            continue

        try:
            children = [p for p in directory.iterdir() if include_hidden or not p.name.startswith(".")]
        except PermissionError:
            continue

        if not children:
            empty_dirs.append(directory)

    return sorted(empty_dirs)

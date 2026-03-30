from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(slots=True)
class DuplicateFileInfo:
    group_id: str
    path: Path
    size_bytes: int
    hash_value: str
    role: str  # "original" | "copy"


@dataclass(slots=True)
class DuplicateGroup:
    group_id: str
    hash_value: str
    size_bytes: int
    files: list[DuplicateFileInfo]


def find_duplicates(
    root_path: str | Path,
    *,
    hash_algo: str = "sha256",
    cancel_check: Callable[[], bool] | None = None,
    progress_cb: Callable[[int], None] | None = None,
    current_path_cb: Callable[[str], None] | None = None,
) -> list[DuplicateGroup]:
    root = Path(root_path)
    size_map: dict[int, list[Path]] = {}

    candidates = list(_iter_files(root))
    total = max(len(candidates), 1)

    for index, path in enumerate(candidates, start=1):
        if _cancelled(cancel_check):
            return []
        if current_path_cb:
            current_path_cb(str(path))

        try:
            size = path.stat().st_size
        except OSError:
            continue

        size_map.setdefault(size, []).append(path)
        if progress_cb:
            progress_cb(int(index / total * 35))

    groups: list[DuplicateGroup] = []
    hash_candidates = [(size, paths) for size, paths in size_map.items() if len(paths) > 1]
    to_hash = sum(len(paths) for _, paths in hash_candidates) or 1
    hashed = 0

    for size, paths in hash_candidates:
        digest_map: dict[str, list[Path]] = {}

        for path in paths:
            if _cancelled(cancel_check):
                return []
            if current_path_cb:
                current_path_cb(str(path))

            digest = _hash_file(path, hash_algo)
            if digest is None:
                continue

            digest_map.setdefault(digest, []).append(path)
            hashed += 1
            if progress_cb:
                progress_cb(35 + int(hashed / to_hash * 65))

        for digest, same_files in digest_map.items():
            if len(same_files) < 2:
                continue

            same_files.sort(key=lambda p: str(p).lower())
            file_infos: list[DuplicateFileInfo] = []
            for i, dup_path in enumerate(same_files):
                role = "original" if i == 0 else "copy"
                file_infos.append(
                    DuplicateFileInfo(
                        group_id=digest[:12],
                        path=dup_path,
                        size_bytes=size,
                        hash_value=digest,
                        role=role,
                    )
                )

            groups.append(
                DuplicateGroup(
                    group_id=digest[:12],
                    hash_value=digest,
                    size_bytes=size,
                    files=file_infos,
                )
            )

    groups.sort(key=lambda g: (g.size_bytes, g.group_id), reverse=True)
    if progress_cb:
        progress_cb(100)
    return groups


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in root.rglob("*"):
        if path.is_file():
            yield path


def _hash_file(path: Path, hash_algo: str) -> str | None:
    try:
        hasher = hashlib.new(hash_algo)
    except ValueError:
        hasher = hashlib.md5()

    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                hasher.update(chunk)
    except OSError:
        return None

    return hasher.hexdigest()


def _cancelled(cancel_check: Callable[[], bool] | None) -> bool:
    return cancel_check is not None and cancel_check()

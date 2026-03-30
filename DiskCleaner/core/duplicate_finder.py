"""Duplicate file finder by size+hash."""

from collections import defaultdict
from hashlib import md5
from pathlib import Path

from DiskCleaner.core.scanner import iter_files


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = md5()
    with path.open("rb") as file_obj:
        while chunk := file_obj.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def find_duplicates(root: str) -> dict[str, list[Path]]:
    grouped_by_size: dict[int, list[Path]] = defaultdict(list)
    for file_path in iter_files(root):
        grouped_by_size[file_path.stat().st_size].append(file_path)

    duplicates: dict[str, list[Path]] = {}
    for size_group in grouped_by_size.values():
        if len(size_group) < 2:
            continue
        hash_map: dict[str, list[Path]] = defaultdict(list)
        for path in size_group:
            hash_map[_hash_file(path)].append(path)
        for file_hash, paths in hash_map.items():
            if len(paths) > 1:
                duplicates[file_hash] = paths
    return duplicates

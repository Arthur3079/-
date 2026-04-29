import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List

from .app_logger import get_logger
from .utils import file_stat_safe, iter_files


@dataclass
class DuplicateEntry:
    path: str
    size: int
    digest: str


class DuplicateFinder:
    def __init__(self):
        self.cancel_requested = False
        self.logger = get_logger("diskcleaner.duplicate_finder")

    def cancel(self):
        self.cancel_requested = True

    @staticmethod
    def _sha256(path: str, chunk_size: int = 1024 * 1024) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def find(self, root: str, progress_cb=None) -> Dict[str, List[DuplicateEntry]]:
        self.cancel_requested = False
        self.logger.info("Duplicate scan started: root=%s", root)
        by_size = defaultdict(list)
        for path in iter_files(root):
            if self.cancel_requested:
                self.logger.info("Duplicate scan canceled during size pass")
                return {}
            if progress_cb:
                progress_cb(path)
            st = file_stat_safe(path)
            if st and st.st_size > 0:
                by_size[st.st_size].append(path)

        groups: Dict[str, List[DuplicateEntry]] = {}
        for size, files in by_size.items():
            if self.cancel_requested:
                self.logger.info("Duplicate scan canceled during hash pass")
                return groups
            if len(files) < 2:
                continue
            by_hash = defaultdict(list)
            for path in files:
                try:
                    digest = self._sha256(path)
                    by_hash[digest].append(path)
                except (PermissionError, FileNotFoundError, OSError):
                    continue
            for digest, paths in by_hash.items():
                if len(paths) > 1:
                    groups[digest] = [DuplicateEntry(path=p, size=size, digest=digest) for p in paths]

        self.logger.info("Duplicate scan completed: groups=%s", len(groups))
        return groups

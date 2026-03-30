from dataclasses import dataclass
from datetime import datetime
from typing import List

from .app_logger import get_logger
from .utils import file_stat_safe, iter_files, months_ago


@dataclass
class OldFileEntry:
    path: str
    size: int
    last_access: datetime


class OldFilesFinder:
    def __init__(self):
        self.cancel_requested = False
        self.logger = get_logger("diskcleaner.old_files")

    def cancel(self):
        self.cancel_requested = True

    def find(self, root: str, months: int = 12, progress_cb=None) -> List[OldFileEntry]:
        self.cancel_requested = False
        self.logger.info("Old file scan started: root=%s months=%s", root, months)
        threshold = months_ago(months)
        out: List[OldFileEntry] = []

        for path in iter_files(root):
            if self.cancel_requested:
                break
            if progress_cb:
                progress_cb(path)
            st = file_stat_safe(path)
            if not st:
                continue
            last_access = datetime.fromtimestamp(st.st_atime)
            if last_access < threshold:
                out.append(OldFileEntry(path=path, size=st.st_size, last_access=last_access))

        out.sort(key=lambda x: x.last_access)
        self.logger.info("Old file scan completed: found=%s", len(out))
        return out

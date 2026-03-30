import os
from dataclasses import dataclass
from datetime import datetime
from typing import List

from .app_logger import get_logger
from .utils import file_stat_safe, iter_files


@dataclass
class LargeFileEntry:
    name: str
    path: str
    size: int
    last_access: datetime
    ext: str


class LargeFilesFinder:
    def __init__(self):
        self.cancel_requested = False
        self.logger = get_logger("diskcleaner.large_files")

    def cancel(self):
        self.cancel_requested = True

    def find(self, root: str, threshold_mb: int = 100, progress_cb=None) -> List[LargeFileEntry]:
        self.cancel_requested = False
        self.logger.info("Large file scan started: root=%s threshold_mb=%s", root, threshold_mb)
        threshold = threshold_mb * 1024 * 1024
        out: List[LargeFileEntry] = []
        for path in iter_files(root):
            if self.cancel_requested:
                break
            if progress_cb:
                progress_cb(path)
            st = file_stat_safe(path)
            if not st:
                continue
            if st.st_size >= threshold:
                out.append(
                    LargeFileEntry(
                        name=os.path.basename(path),
                        path=path,
                        size=st.st_size,
                        last_access=datetime.fromtimestamp(st.st_atime),
                        ext=os.path.splitext(path)[1].lower(),
                    )
                )
        out.sort(key=lambda x: x.size, reverse=True)
        self.logger.info("Large file scan completed: found=%s", len(out))
        return out

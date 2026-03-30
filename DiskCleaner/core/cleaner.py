import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from config import LOG_FILE, QUARANTINE_DIR


class Cleaner:
    def __init__(self, log_file: Path = LOG_FILE, quarantine_dir: Path = QUARANTINE_DIR):
        self.log_file = log_file
        self.quarantine_dir = quarantine_dir
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)

    def _log(self, line: str):
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} | {line}\n")

    def delete_files(self, paths: List[str], quarantine: bool = False) -> Tuple[List[str], Dict[str, str]]:
        deleted = []
        failed: Dict[str, str] = {}
        for p in paths:
            try:
                if quarantine:
                    target = self.quarantine_dir / os.path.basename(p)
                    if target.exists():
                        target = self.quarantine_dir / f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.path.basename(p)}"
                    shutil.move(p, target)
                    self._log(f"QUARANTINE {p} -> {target}")
                else:
                    if os.path.isdir(p):
                        shutil.rmtree(p)
                    else:
                        os.remove(p)
                    self._log(f"DELETE {p}")
                deleted.append(p)
            except (PermissionError, FileNotFoundError, OSError) as e:
                failed[p] = str(e)
                self._log(f"FAILED {p}: {e}")
        return deleted, failed

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

from core.junk_finder import JunkFinding


@dataclass(frozen=True)
class CleanupResult:
    path: str
    action: str
    success: bool
    message: str


class Cleaner:
    def __init__(self, log_path: str = "logs/cleanup_log.txt", quarantine_dir: str = ".quarantine") -> None:
        self.log_path = Path(log_path)
        self.quarantine_dir = Path(quarantine_dir)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)

    def cleanup(
        self,
        findings: Iterable[JunkFinding],
        mode: str,
        confirmed: bool,
    ) -> List[CleanupResult]:
        if not confirmed:
            raise ValueError("Cleanup requires explicit confirmation.")
        if mode not in {"delete", "quarantine"}:
            raise ValueError("Unsupported mode. Use 'delete' or 'quarantine'.")

        results: List[CleanupResult] = []
        for item in findings:
            if not item.exists:
                result = CleanupResult(item.path, mode, False, "Skipped: path not found")
                results.append(result)
                self._log(result)
                continue

            if not item.deletable or item.risk_level == "danger":
                result = CleanupResult(item.path, mode, False, "Skipped: dangerous/info-only category")
                results.append(result)
                self._log(result)
                continue

            try:
                if mode == "delete":
                    self._delete_path(item.path)
                    result = CleanupResult(item.path, "delete", True, "Deleted")
                else:
                    target = self._quarantine_path(item.path)
                    result = CleanupResult(item.path, "quarantine", True, f"Moved to quarantine: {target}")
            except PermissionError:
                result = CleanupResult(item.path, mode, False, "Skipped: file in use / permission denied")
            except FileNotFoundError:
                result = CleanupResult(item.path, mode, False, "Skipped: path disappeared")
            except OSError as exc:
                result = CleanupResult(item.path, mode, False, f"Error: {exc}")

            results.append(result)
            self._log(result)

        return results

    def _delete_path(self, path: str) -> None:
        target = Path(path)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    def _quarantine_path(self, path: str) -> str:
        source = Path(path)
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        destination = self.quarantine_dir / f"{stamp}_{source.name}"
        shutil.move(str(source), str(destination))
        return str(destination)

    def _log(self, result: CleanupResult) -> None:
        timestamp = datetime.utcnow().isoformat()
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"{timestamp}\t{result.action}\t{result.success}\t{result.path}\t{result.message}\n")

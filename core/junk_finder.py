from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from core.scanner import DirectoryScanner


RISK_SAFE = "safe"
RISK_CAUTION = "caution"
RISK_DANGER = "danger"


@dataclass(frozen=True)
class JunkRule:
    category: str
    patterns: tuple[str, ...]
    risk_level: str
    deletable: bool
    warning: str = ""


@dataclass(frozen=True)
class JunkFinding:
    path: str
    size: int
    category: str
    risk_level: str
    deletable: bool
    warning: str
    exists: bool
    access_error: bool


DANGEROUS_CATEGORIES = {
    "WinSxS",
    "Windows Installer",
    "System Files",
}


JUNK_RULES: tuple[JunkRule, ...] = (
    JunkRule("Temp", (r"%TEMP%\\*", r"C:\\Windows\\Temp\\*"), RISK_SAFE, True),
    JunkRule("Browser Cache", (r"%LOCALAPPDATA%\\*\\*Cache*",), RISK_SAFE, True),
    JunkRule("Windows Cache", (r"C:\\Windows\\SoftwareDistribution\\Download\\*",), RISK_CAUTION, True),
    JunkRule("Recycle Bin", (r"C:\\$Recycle.Bin\\*",), RISK_CAUTION, True),
    JunkRule("Logs", (r"C:\\Windows\\Logs\\*", r"%LOCALAPPDATA%\\*\\Logs\\*"), RISK_SAFE, True),
    JunkRule("Thumbnails", (r"%LOCALAPPDATA%\\Microsoft\\Windows\\Explorer\\thumbcache*",), RISK_SAFE, True),
    JunkRule("App Caches", (r"%LOCALAPPDATA%\\*\\Cache\\*", r"%APPDATA%\\*\\Cache\\*"), RISK_CAUTION, True),
    JunkRule("Update Files", (r"C:\\Windows\\SoftwareDistribution\\*",), RISK_CAUTION, True),
    JunkRule("Dumps", (r"C:\\Windows\\Minidump\\*", r"%LOCALAPPDATA%\\CrashDumps\\*"), RISK_CAUTION, True),
    JunkRule("Hibernation/Page/Swap Info", (r"C:\\hiberfil.sys", r"C:\\pagefile.sys", r"C:\\swapfile.sys"), RISK_DANGER, False, "System memory files: auto-deletion forbidden."),
    JunkRule("Installers/Downloads", (r"%USERPROFILE%\\Downloads\\*.msi", r"%USERPROFILE%\\Downloads\\*.exe"), RISK_CAUTION, True),
    JunkRule("Restore Points Info", (r"C:\\System Volume Information\\*",), RISK_DANGER, False, "System restore data: informational only."),
    JunkRule("DirectX Shader Cache", (r"%LOCALAPPDATA%\\D3DSCache\\*",), RISK_SAFE, True),
    JunkRule("Orphaned App Leftovers", (r"%LOCALAPPDATA%\\*\\Uninstall*", r"%PROGRAMDATA%\\*\\Logs\\*"), RISK_CAUTION, True),
    JunkRule("WinSxS", (r"C:\\Windows\\WinSxS\\*",), RISK_DANGER, False, "WinSxS is critical: auto-deletion forbidden."),
    JunkRule("Windows Installer", (r"C:\\Windows\\Installer\\*",), RISK_DANGER, False, "Windows Installer cache: auto-deletion forbidden."),
    JunkRule("System Files", (r"C:\\Windows\\System32\\*.sys",), RISK_DANGER, False, "System files: informational only."),
)


class JunkFinder:
    def __init__(self, scanner: DirectoryScanner | None = None) -> None:
        self.scanner = scanner or DirectoryScanner()

    def find(self, rules: Iterable[JunkRule] = JUNK_RULES) -> List[JunkFinding]:
        findings: List[JunkFinding] = []
        seen_paths: set[str] = set()

        for rule in rules:
            for pattern in rule.patterns:
                expanded_pattern = os.path.expandvars(pattern)
                for candidate in glob.glob(expanded_pattern):
                    resolved = str(Path(candidate).resolve())
                    if resolved in seen_paths:
                        continue
                    seen_paths.add(resolved)

                    exists = Path(candidate).exists()
                    access_error = False
                    size = 0

                    if exists:
                        try:
                            size = self.scanner.path_size(candidate)
                        except PermissionError:
                            access_error = True

                    findings.append(
                        JunkFinding(
                            path=resolved,
                            size=size,
                            category=rule.category,
                            risk_level=rule.risk_level,
                            deletable=rule.deletable and rule.category not in DANGEROUS_CATEGORIES,
                            warning=rule.warning,
                            exists=exists,
                            access_error=access_error,
                        )
                    )

        return findings

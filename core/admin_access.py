from __future__ import annotations

import ctypes
import os
from pathlib import Path


def has_admin_rights() -> bool:
    """Проверяет наличие прав администратора/root."""

    if os.name == "nt":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # pragma: no cover
            return False
    return os.geteuid() == 0


def inaccessible_system_paths(paths: list[Path]) -> list[Path]:
    """Возвращает системные пути, недоступные для чтения текущему пользователю."""

    inaccessible: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        if not os.access(path, os.R_OK):
            inaccessible.append(path)
    return inaccessible


def admin_hint_message() -> str:
    return "Для полного сканирования системных путей перезапустите приложение от имени администратора."

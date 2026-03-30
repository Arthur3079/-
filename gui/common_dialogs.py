from __future__ import annotations

from pathlib import Path

from PyQt5.QtWidgets import QMessageBox


def human_size(size_bytes: int) -> str:
    size = float(size_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size_bytes} B"


def confirm_delete(parent, paths: list[Path]) -> bool:
    total = sum(path.stat().st_size for path in paths if path.exists())
    preview = "\n".join(str(path) for path in paths[:20])
    if len(paths) > 20:
        preview += f"\n... и ещё {len(paths) - 20}"

    message = QMessageBox(parent)
    message.setIcon(QMessageBox.Warning)
    message.setWindowTitle("Подтверждение удаления")
    message.setText(f"Будет удалено файлов: {len(paths)}")
    message.setInformativeText(f"Общий объём: {human_size(total)}")
    message.setDetailedText(preview)
    message.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    message.setDefaultButton(QMessageBox.No)

    return message.exec_() == QMessageBox.Yes

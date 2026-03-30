from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PyQt5.QtCore import QThread, Qt
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.large_files import LargeFileInfo, find_large_files
from gui.common_dialogs import confirm_delete, human_size
from gui.workers import OperationWorker


class LargeFilesTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._results: list[LargeFileInfo] = []
        self._thread: QThread | None = None
        self._worker: OperationWorker | None = None

        self.path_label = QLabel("Папка не выбрана")
        self.progress_label = QLabel("")

        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(1, 10_000)
        self.threshold_spin.setValue(100)
        self.threshold_spin.setSuffix(" MB")

        self.threshold_slider = QSlider(Qt.Horizontal)
        self.threshold_slider.setRange(1, 1_000)
        self.threshold_slider.setValue(100)

        self.browse_btn = QPushButton("Выбрать папку")
        self.scan_btn = QPushButton("Сканировать")
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.setEnabled(False)

        self.open_folder_btn = QPushButton("Открыть папку")
        self.delete_btn = QPushButton("Удалить выбранные")
        self.quarantine_btn = QPushButton("В карантин")

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Путь", "Размер", "Last Access", "Тип"])
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        self._build_ui()
        self._bind_events()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self.browse_btn)
        top.addWidget(self.path_label, 1)
        layout.addLayout(top)

        threshold = QHBoxLayout()
        threshold.addWidget(QLabel("Порог:"))
        threshold.addWidget(self.threshold_spin)
        threshold.addWidget(self.threshold_slider, 1)
        threshold.addWidget(self.scan_btn)
        threshold.addWidget(self.cancel_btn)
        layout.addLayout(threshold)

        layout.addWidget(self.table)

        actions = QHBoxLayout()
        actions.addWidget(self.open_folder_btn)
        actions.addWidget(self.quarantine_btn)
        actions.addWidget(self.delete_btn)
        layout.addLayout(actions)
        layout.addWidget(self.progress_label)

    def _bind_events(self) -> None:
        self.threshold_spin.valueChanged.connect(self.threshold_slider.setValue)
        self.threshold_slider.valueChanged.connect(self.threshold_spin.setValue)
        self.browse_btn.clicked.connect(self._choose_folder)
        self.scan_btn.clicked.connect(self._start_scan)
        self.cancel_btn.clicked.connect(self._cancel_scan)
        self.open_folder_btn.clicked.connect(self._open_selected_folder)
        self.delete_btn.clicked.connect(self._delete_selected)
        self.quarantine_btn.clicked.connect(self._quarantine_selected)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Выбор папки")
        if folder:
            self.path_label.setText(folder)

    def _start_scan(self) -> None:
        root = self.path_label.text().strip()
        if not root or root == "Папка не выбрана":
            QMessageBox.information(self, "Сканирование", "Сначала выберите папку")
            return

        self._set_busy(True)
        self._thread = QThread(self)
        self._worker = OperationWorker(find_large_files, root, self.threshold_spin.value())
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda p: self.progress_label.setText(f"Прогресс: {p}%"))
        self._worker.current_path.connect(lambda p: self.progress_label.setText(f"Сканирование: {p}"))
        self._worker.finished.connect(self._on_scan_finished)
        self._worker.cancelled.connect(lambda: self.progress_label.setText("Операция отменена"))
        self._worker.failed.connect(lambda e: QMessageBox.critical(self, "Ошибка", e))
        self._worker.finished.connect(self._cleanup_worker)
        self._worker.failed.connect(self._cleanup_worker)
        self._worker.cancelled.connect(self._cleanup_worker)

        self._thread.start()

    def _cancel_scan(self) -> None:
        if self._worker:
            self._worker.cancel()

    def _cleanup_worker(self, *_args) -> None:
        self._set_busy(False)
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._worker = None
        self._thread = None

    def _set_busy(self, busy: bool) -> None:
        self.scan_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)

    def _on_scan_finished(self, results: list[LargeFileInfo]) -> None:
        self._results = results
        self.table.setRowCount(len(results))
        for row, item in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(str(item.path)))
            self.table.setItem(row, 1, QTableWidgetItem(human_size(item.size_bytes)))
            self.table.setItem(row, 2, QTableWidgetItem(item.last_access.strftime("%Y-%m-%d %H:%M:%S")))
            self.table.setItem(row, 3, QTableWidgetItem(item.file_type))

    def _selected_paths(self) -> list[Path]:
        selected = []
        for idx in self.table.selectionModel().selectedRows():
            path = self.table.item(idx.row(), 0).text()
            selected.append(Path(path))
        return selected

    def _open_selected_folder(self) -> None:
        paths = self._selected_paths()
        if not paths:
            return
        folder = paths[0].parent
        if sys.platform.startswith("win"):
            os.startfile(str(folder))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)

    def _delete_selected(self) -> None:
        paths = self._selected_paths()
        if not paths or not confirm_delete(self, paths):
            return

        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        self._start_scan()

    def _quarantine_selected(self) -> None:
        paths = self._selected_paths()
        if not paths:
            return

        quarantine = Path(self.path_label.text()) / "_quarantine"
        quarantine.mkdir(exist_ok=True)

        for src in paths:
            if not src.exists():
                continue
            target = quarantine / src.name
            suffix = 1
            while target.exists():
                target = quarantine / f"{src.stem}_{suffix}{src.suffix}"
                suffix += 1
            shutil.move(str(src), str(target))
        self._start_scan()

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QThread
from PyQt5.QtWidgets import (
    QFileDialog,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.old_files import OldFileInfo, find_old_files
from gui.common_dialogs import confirm_delete, human_size
from gui.workers import OperationWorker


class OldFilesTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._results: list[OldFileInfo] = []
        self._thread: QThread | None = None
        self._worker: OperationWorker | None = None

        self.path_label = QLabel("Папка не выбрана")
        self.status_label = QLabel("")

        self.period_combo = QComboBox()
        self.period_combo.addItems(["6 месяцев", "12 месяцев", "Настроить"])
        self.custom_months = QSpinBox()
        self.custom_months.setRange(1, 120)
        self.custom_months.setValue(6)
        self.custom_months.setEnabled(False)

        self.browse_btn = QPushButton("Выбрать папку")
        self.scan_btn = QPushButton("Найти старые файлы")
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.setEnabled(False)
        self.delete_btn = QPushButton("Удалить выбранные")

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Путь", "Размер", "Last Access", "Порог (мес.)"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSortingEnabled(True)

        self._build_ui()
        self._bind_events()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self.browse_btn)
        top.addWidget(self.path_label, 1)
        layout.addLayout(top)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Период:"))
        filters.addWidget(self.period_combo)
        filters.addWidget(self.custom_months)
        filters.addWidget(self.scan_btn)
        filters.addWidget(self.cancel_btn)
        layout.addLayout(filters)

        layout.addWidget(self.table)
        layout.addWidget(self.delete_btn)
        layout.addWidget(self.status_label)

    def _bind_events(self) -> None:
        self.browse_btn.clicked.connect(self._choose_folder)
        self.period_combo.currentTextChanged.connect(self._on_period_changed)
        self.scan_btn.clicked.connect(self._start_scan)
        self.cancel_btn.clicked.connect(self._cancel)
        self.delete_btn.clicked.connect(self._delete_selected)

    def _on_period_changed(self, value: str) -> None:
        self.custom_months.setEnabled(value == "Настроить")

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Выбор папки")
        if folder:
            self.path_label.setText(folder)

    def _get_months(self) -> int:
        value = self.period_combo.currentText()
        if value.startswith("6"):
            return 6
        if value.startswith("12"):
            return 12
        return self.custom_months.value()

    def _start_scan(self) -> None:
        root = self.path_label.text().strip()
        if root == "Папка не выбрана":
            QMessageBox.information(self, "Поиск", "Сначала выберите папку")
            return

        self._set_busy(True)
        months = self._get_months()
        self._thread = QThread(self)
        self._worker = OperationWorker(find_old_files, root, months)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda p: self.status_label.setText(f"Прогресс: {p}%"))
        self._worker.current_path.connect(lambda p: self.status_label.setText(f"Проверка: {p}"))
        self._worker.finished.connect(self._on_results)
        self._worker.failed.connect(lambda e: QMessageBox.critical(self, "Ошибка", e))
        self._worker.cancelled.connect(lambda: self.status_label.setText("Операция отменена"))
        self._worker.finished.connect(self._cleanup)
        self._worker.failed.connect(self._cleanup)
        self._worker.cancelled.connect(self._cleanup)

        self._thread.start()

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancel()

    def _cleanup(self, *_args) -> None:
        self._set_busy(False)
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None

    def _set_busy(self, busy: bool) -> None:
        self.scan_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)

    def _on_results(self, results: list[OldFileInfo]) -> None:
        self._results = results
        self.table.setRowCount(len(results))
        for row, item in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(str(item.path)))
            self.table.setItem(row, 1, QTableWidgetItem(human_size(item.size_bytes)))
            self.table.setItem(row, 2, QTableWidgetItem(item.last_access.strftime("%Y-%m-%d %H:%M:%S")))
            self.table.setItem(row, 3, QTableWidgetItem(str(item.months_unused)))

    def _selected_paths(self) -> list[Path]:
        paths: list[Path] = []
        for row in self.table.selectionModel().selectedRows():
            paths.append(Path(self.table.item(row.row(), 0).text()))
        return paths

    def _delete_selected(self) -> None:
        paths = self._selected_paths()
        if not paths or not confirm_delete(self, paths):
            return

        failed = 0
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                failed += 1

        if failed:
            QMessageBox.warning(self, "Удаление", f"Ошибок удаления: {failed}")
        self._start_scan()

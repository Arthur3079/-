from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QThread, Qt
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.duplicate_finder import DuplicateFileInfo, DuplicateGroup, find_duplicates
from gui.common_dialogs import confirm_delete, human_size
from gui.workers import OperationWorker


class DuplicatesTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._groups: list[DuplicateGroup] = []
        self._thread: QThread | None = None
        self._worker: OperationWorker | None = None

        self.path_label = QLabel("Папка не выбрана")
        self.status_label = QLabel("")

        self.browse_btn = QPushButton("Выбрать папку")
        self.scan_btn = QPushButton("Найти дубликаты")
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.setEnabled(False)
        self.delete_btn = QPushButton("Удалить выбранные копии")

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Удалить", "Группа", "Роль", "Путь", "Размер", "Хеш"])
        self.table.setSortingEnabled(True)

        self._build_ui()
        self._bind_events()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self.browse_btn)
        top.addWidget(self.path_label, 1)
        top.addWidget(self.scan_btn)
        top.addWidget(self.cancel_btn)
        layout.addLayout(top)
        layout.addWidget(self.table)
        layout.addWidget(self.delete_btn)
        layout.addWidget(self.status_label)

    def _bind_events(self) -> None:
        self.browse_btn.clicked.connect(self._choose_folder)
        self.scan_btn.clicked.connect(self._start_scan)
        self.cancel_btn.clicked.connect(self._cancel)
        self.delete_btn.clicked.connect(self._delete_selected)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Выбор папки")
        if folder:
            self.path_label.setText(folder)

    def _start_scan(self) -> None:
        root = self.path_label.text().strip()
        if root == "Папка не выбрана":
            QMessageBox.information(self, "Поиск", "Сначала выберите папку")
            return

        self._set_busy(True)
        self._thread = QThread(self)
        self._worker = OperationWorker(find_duplicates, root)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda p: self.status_label.setText(f"Прогресс: {p}%"))
        self._worker.current_path.connect(lambda p: self.status_label.setText(f"Обработка: {p}"))
        self._worker.finished.connect(self._show_results)
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

    def _show_results(self, groups: list[DuplicateGroup]) -> None:
        self._groups = groups
        all_files: list[DuplicateFileInfo] = []
        for group in groups:
            all_files.extend(group.files)

        self.table.setRowCount(len(all_files))
        for row, item in enumerate(all_files):
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            check_item.setCheckState(Qt.Unchecked)
            self.table.setItem(row, 0, check_item)

            self.table.setItem(row, 1, QTableWidgetItem(item.group_id))
            self.table.setItem(row, 2, QTableWidgetItem(item.role))
            self.table.setItem(row, 3, QTableWidgetItem(str(item.path)))
            self.table.setItem(row, 4, QTableWidgetItem(human_size(item.size_bytes)))
            self.table.setItem(row, 5, QTableWidgetItem(item.hash_value[:16]))

            if item.role == "original":
                check_item.setFlags(Qt.ItemIsEnabled)
                check_item.setCheckState(Qt.Unchecked)

    def _selected_paths_for_delete(self) -> list[Path]:
        selected: list[Path] = []
        for row in range(self.table.rowCount()):
            marker = self.table.item(row, 0)
            role = self.table.item(row, 2)
            if not marker or not role:
                continue
            if role.text() == "original":
                continue
            if marker.checkState() == Qt.Checked:
                selected.append(Path(self.table.item(row, 3).text()))
        return selected

    def _delete_selected(self) -> None:
        paths = self._selected_paths_for_delete()
        if not paths or not confirm_delete(self, paths):
            return

        errors = 0
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                errors += 1

        if errors:
            QMessageBox.warning(self, "Удаление", f"Не удалось удалить: {errors}")
        self._start_scan()

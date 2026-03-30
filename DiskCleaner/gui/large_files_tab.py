import os
import subprocess

from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
)

from core.cleaner import Cleaner
from core.large_files import LargeFilesFinder
from core.utils import human_size


class LargeWorker(QThread):
    finished_scan = pyqtSignal(list)

    def __init__(self, root, threshold):
        super().__init__()
        self.finder = LargeFilesFinder()
        self.root = root
        self.threshold = threshold

    def run(self):
        self.finished_scan.emit(self.finder.find(self.root, self.threshold))


class LargeFilesTab(QWidget):
    def __init__(self, get_root):
        super().__init__()
        self.get_root = get_root
        self.worker = None
        self.entries = []
        self.cleaner = Cleaner()

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 102400)
        self.threshold.setValue(50)
        self.scan_btn = QPushButton("Найти")
        self.select_all_btn = QPushButton("Отметить все")
        self.clear_all_btn = QPushButton("Снять все")
        self.select_media_btn = QPushButton("Отметить ISO/ZIP/Видео")
        self.open_btn = QPushButton("Открыть папку")
        self.delete_btn = QPushButton("Удалить отмеченные")
        self.total_label = QLabel("Отмечено: 0 B")

        top.addWidget(QLabel("Порог (МБ):"))
        top.addWidget(self.threshold)
        top.addWidget(self.scan_btn)
        top.addWidget(self.select_all_btn)
        top.addWidget(self.clear_all_btn)
        top.addWidget(self.select_media_btn)
        top.addWidget(self.open_btn)
        top.addWidget(self.delete_btn)
        top.addWidget(self.total_label)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["✓", "Имя", "Путь", "Размер", "Последний доступ", "Тип"])
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(self.table.SelectRows)

        layout.addLayout(top)
        layout.addWidget(self.table)

        self.scan_btn.clicked.connect(self.scan)
        self.select_all_btn.clicked.connect(self.check_all)
        self.clear_all_btn.clicked.connect(self.uncheck_all)
        self.select_media_btn.clicked.connect(self.check_media_like)
        self.open_btn.clicked.connect(self.open_folder)
        self.delete_btn.clicked.connect(self.delete_checked)
        self.table.itemChanged.connect(self.recalc_checked_size)

    def scan(self):
        self.worker = LargeWorker(self.get_root(), self.threshold.value())
        self.worker.finished_scan.connect(self.on_done)
        self.worker.start()

    def on_done(self, entries):
        self.entries = entries
        self.table.blockSignals(True)
        self.table.setRowCount(len(entries))
        for i, e in enumerate(entries):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Unchecked)
            self.table.setItem(i, 0, check)
            self.table.setItem(i, 1, QTableWidgetItem(e.name))
            self.table.setItem(i, 2, QTableWidgetItem(e.path))
            self.table.setItem(i, 3, QTableWidgetItem(human_size(e.size)))
            self.table.setItem(i, 4, QTableWidgetItem(e.last_access.strftime("%Y-%m-%d %H:%M")))
            self.table.setItem(i, 5, QTableWidgetItem(e.ext))
        self.table.blockSignals(False)
        self.recalc_checked_size()

    def check_all(self):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(Qt.Checked)
        self.table.blockSignals(False)
        self.recalc_checked_size()

    def uncheck_all(self):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(Qt.Unchecked)
        self.table.blockSignals(False)
        self.recalc_checked_size()

    def check_media_like(self):
        targets = {".iso", ".zip", ".rar", ".7z", ".mp4", ".mov", ".mkv", ".vhdx"}
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            ext = (self.table.item(r, 5).text() or "").lower()
            self.table.item(r, 0).setCheckState(Qt.Checked if ext in targets else Qt.Unchecked)
        self.table.blockSignals(False)
        self.recalc_checked_size()

    def checked_paths(self):
        paths = []
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).checkState() == Qt.Checked:
                paths.append(self.table.item(r, 2).text())
        return paths

    def recalc_checked_size(self):
        total = 0
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).checkState() == Qt.Checked:
                size_txt = self.table.item(r, 3).text()
                try:
                    val, unit = size_txt.split()
                    mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}.get(unit, 1)
                    total += int(float(val) * mult)
                except Exception:
                    continue
        self.total_label.setText(f"Отмечено: {human_size(total)}")

    def open_folder(self):
        paths = self.checked_paths()
        if not paths:
            indexes = self.table.selectedIndexes()
            if indexes:
                row = indexes[0].row()
                paths = [self.table.item(row, 2).text()]
        if not paths:
            return
        folder = os.path.dirname(paths[0])
        try:
            if os.name == "nt":
                os.startfile(folder)
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", str(e))

    def delete_checked(self):
        paths = self.checked_paths()
        if not paths:
            QMessageBox.information(self, "Нечего удалять", "Отметьте файлы галочками в первом столбце.")
            return
        preview = "\n".join(paths[:20])
        if len(paths) > 20:
            preview += f"\n... и ещё {len(paths) - 20}"
        if QMessageBox.question(self, "Подтверждение", f"Удалить {len(paths)} файлов?\n\n{preview}") != QMessageBox.Yes:
            return
        deleted, failed = self.cleaner.delete_files(paths)
        QMessageBox.information(self, "Итог", f"Удалено: {len(deleted)}; ошибок: {len(failed)}")
        self.scan()

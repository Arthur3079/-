import os
import subprocess

from PyQt5.QtCore import QThread, pyqtSignal
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
        self.threshold.setValue(100)
        self.scan_btn = QPushButton("Найти")
        self.open_btn = QPushButton("Открыть папку")
        self.select_all_btn = QPushButton("Выбрать все")
        self.delete_btn = QPushButton("Удалить выбранные")
        top.addWidget(QLabel("Порог (МБ):"))
        top.addWidget(self.threshold)
        top.addWidget(self.scan_btn)
        top.addWidget(self.open_btn)
        top.addWidget(self.select_all_btn)
        top.addWidget(self.delete_btn)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Имя", "Путь", "Размер", "Последний доступ", "Тип"])
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(self.table.SelectRows)

        layout.addLayout(top)
        layout.addWidget(self.table)

        self.scan_btn.clicked.connect(self.scan)
        self.open_btn.clicked.connect(self.open_folder)
        self.select_all_btn.clicked.connect(self.table.selectAll)
        self.delete_btn.clicked.connect(self.delete_selected)

    def scan(self):
        self.worker = LargeWorker(self.get_root(), self.threshold.value())
        self.worker.finished_scan.connect(self.on_done)
        self.worker.start()

    def on_done(self, entries):
        self.entries = entries
        self.table.setRowCount(len(entries))
        for i, e in enumerate(entries):
            self.table.setItem(i, 0, QTableWidgetItem(e.name))
            self.table.setItem(i, 1, QTableWidgetItem(e.path))
            self.table.setItem(i, 2, QTableWidgetItem(human_size(e.size)))
            self.table.setItem(i, 3, QTableWidgetItem(e.last_access.strftime("%Y-%m-%d %H:%M")))
            self.table.setItem(i, 4, QTableWidgetItem(e.ext))

    def selected_paths(self):
        rows = sorted(set(i.row() for i in self.table.selectedIndexes()))
        return [self.table.item(r, 1).text() for r in rows]

    def open_folder(self):
        paths = self.selected_paths()
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

    def delete_selected(self):
        paths = self.selected_paths()
        if not paths:
            return
        preview = "\n".join(paths[:20])
        if len(paths) > 20:
            preview += f"\n... и ещё {len(paths) - 20}"
        if QMessageBox.question(self, "Подтверждение", f"Удалить {len(paths)} файлов?\n\n{preview}") != QMessageBox.Yes:
            return
        deleted, failed = self.cleaner.delete_files(paths)
        QMessageBox.information(self, "Итог", f"Удалено: {len(deleted)}; ошибок: {len(failed)}")

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
from core.old_files import OldFilesFinder
from core.utils import human_size


class OldWorker(QThread):
    finished_scan = pyqtSignal(list)

    def __init__(self, root, months):
        super().__init__()
        self.finder = OldFilesFinder()
        self.root = root
        self.months = months

    def run(self):
        self.finished_scan.emit(self.finder.find(self.root, self.months))


class OldFilesTab(QWidget):
    def __init__(self, get_root):
        super().__init__()
        self.get_root = get_root
        self.cleaner = Cleaner()

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.months = QSpinBox()
        self.months.setRange(1, 60)
        self.months.setValue(12)
        self.scan_btn = QPushButton("Найти")
        self.select_all_btn = QPushButton("Выбрать все")
        self.delete_btn = QPushButton("Удалить выбранные")
        top.addWidget(QLabel("Не использовались (месяцев):"))
        top.addWidget(self.months)
        top.addWidget(self.scan_btn)
        top.addWidget(self.select_all_btn)
        top.addWidget(self.delete_btn)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Путь", "Размер", "Последний доступ"])
        self.table.setSelectionBehavior(self.table.SelectRows)

        layout.addLayout(top)
        layout.addWidget(self.table)

        self.scan_btn.clicked.connect(self.scan)
        self.select_all_btn.clicked.connect(self.table.selectAll)
        self.delete_btn.clicked.connect(self.delete_selected)

    def scan(self):
        self.worker = OldWorker(self.get_root(), self.months.value())
        self.worker.finished_scan.connect(self.on_done)
        self.worker.start()

    def on_done(self, entries):
        self.table.setRowCount(len(entries))
        for i, e in enumerate(entries):
            self.table.setItem(i, 0, QTableWidgetItem(e.path))
            self.table.setItem(i, 1, QTableWidgetItem(human_size(e.size)))
            self.table.setItem(i, 2, QTableWidgetItem(e.last_access.strftime("%Y-%m-%d %H:%M")))

    def delete_selected(self):
        rows = sorted(set(i.row() for i in self.table.selectedIndexes()))
        paths = [self.table.item(r, 0).text() for r in rows]
        if not paths:
            return
        preview = "\n".join(paths[:20])
        if len(paths) > 20:
            preview += f"\n... и ещё {len(paths) - 20}"
        if QMessageBox.question(self, "Подтверждение", f"Удалить {len(paths)} старых файлов?\n\n{preview}") != QMessageBox.Yes:
            return
        deleted, failed = self.cleaner.delete_files(paths)
        QMessageBox.information(self, "Итог", f"Удалено: {len(deleted)}; ошибок: {len(failed)}")

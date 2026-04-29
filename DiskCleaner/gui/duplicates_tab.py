from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QMessageBox,
)

from core.cleaner import Cleaner
from core.duplicate_finder import DuplicateFinder
from core.utils import human_size


class DuplicatesWorker(QThread):
    finished_scan = pyqtSignal(dict)

    def __init__(self, root):
        super().__init__()
        self.finder = DuplicateFinder()
        self.root = root

    def run(self):
        self.finished_scan.emit(self.finder.find(self.root))


class DuplicatesTab(QWidget):
    def __init__(self, get_root):
        super().__init__()
        self.get_root = get_root
        self.cleaner = Cleaner()

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.scan_btn = QPushButton("Сканировать дубликаты")
        self.select_copies_btn = QPushButton("Выбрать копии")
        self.delete_btn = QPushButton("Удалить выбранные")
        top.addWidget(self.scan_btn)
        top.addWidget(self.select_copies_btn)
        top.addWidget(self.delete_btn)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Файл/Группа", "Размер", "Хеш", "Примечание"])

        layout.addLayout(top)
        layout.addWidget(self.tree)

        self.scan_btn.clicked.connect(self.scan)
        self.select_copies_btn.clicked.connect(self.select_copies)
        self.delete_btn.clicked.connect(self.delete_selected)

    def scan(self):
        self.tree.clear()
        self.worker = DuplicatesWorker(self.get_root())
        self.worker.finished_scan.connect(self.on_done)
        self.worker.start()

    def on_done(self, groups):
        for digest, entries in groups.items():
            group = QTreeWidgetItem([f"Группа {digest[:8]}", human_size(sum(x.size for x in entries)), digest, "Оставьте первый как оригинал"])
            group.setFlags(group.flags() | Qt.ItemIsTristate | Qt.ItemIsUserCheckable)
            group.setCheckState(0, Qt.Unchecked)
            self.tree.addTopLevelItem(group)
            for idx, e in enumerate(entries):
                note = "ОРИГИНАЛ" if idx == 0 else "Копия"
                child = QTreeWidgetItem([e.path, human_size(e.size), digest, note])
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Unchecked if idx == 0 else Qt.Checked)
                group.addChild(child)

    def select_copies(self):
        for i in range(self.tree.topLevelItemCount()):
            grp = self.tree.topLevelItem(i)
            for j in range(grp.childCount()):
                ch = grp.child(j)
                ch.setCheckState(0, Qt.Checked if ch.text(3) == "Копия" else Qt.Unchecked)

    def delete_selected(self):
        paths = []
        for i in range(self.tree.topLevelItemCount()):
            grp = self.tree.topLevelItem(i)
            for j in range(grp.childCount()):
                ch = grp.child(j)
                if ch.checkState(0) == Qt.Checked and ch.text(3) != "ОРИГИНАЛ":
                    paths.append(ch.text(0))
        if not paths:
            return
        preview = "\n".join(paths[:20])
        if len(paths) > 20:
            preview += f"\n... и ещё {len(paths) - 20}"
        if QMessageBox.question(self, "Подтверждение", f"Удалить {len(paths)} копий?\n\n{preview}") != QMessageBox.Yes:
            return
        deleted, failed = self.cleaner.delete_files(paths)
        QMessageBox.information(self, "Итог", f"Удалено: {len(deleted)}; ошибок: {len(failed)}")

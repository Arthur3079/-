from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QLabel,
    QMessageBox,
    QCheckBox,
)

from core.cleaner import Cleaner
from core.junk_finder import JunkFinder
from core.utils import human_size


class JunkWorker(QThread):
    finished_scan = pyqtSignal(dict)

    def __init__(self, root):
        super().__init__()
        self.finder = JunkFinder()
        self.root = root

    def run(self):
        self.finished_scan.emit(self.finder.scan(self.root))

    def cancel(self):
        self.finder.cancel()


class JunkTab(QWidget):
    def __init__(self, get_root):
        super().__init__()
        self.get_root = get_root
        self.worker = None
        self.results = {}
        self.cleaner = Cleaner()

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.scan_btn = QPushButton("Сканировать")
        self.select_safe_btn = QPushButton("Выбрать безопасное")
        self.select_all_btn = QPushButton("Выбрать всё")
        self.clear_btn = QPushButton("Снять всё")
        self.delete_btn = QPushButton("Удалить выбранное")
        self.quarantine_box = QCheckBox("В карантин")
        self.total_label = QLabel("Выбрано: 0 B")

        top.addWidget(self.scan_btn)
        top.addWidget(self.select_safe_btn)
        top.addWidget(self.select_all_btn)
        top.addWidget(self.clear_btn)
        top.addWidget(self.delete_btn)
        top.addWidget(self.quarantine_box)
        top.addWidget(self.total_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Элемент", "Размер", "Безопасность", "Примечание"])

        layout.addLayout(top)
        layout.addWidget(self.tree)

        self.scan_btn.clicked.connect(self.scan)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.select_safe_btn.clicked.connect(self.select_safe)
        self.select_all_btn.clicked.connect(lambda: self.set_all(Qt.Checked))
        self.clear_btn.clicked.connect(lambda: self.set_all(Qt.Unchecked))
        self.tree.itemChanged.connect(self.recalc)

    def scan(self):
        self.tree.clear()
        self.worker = JunkWorker(self.get_root())
        self.worker.finished_scan.connect(self.on_done)
        self.worker.start()

    def on_done(self, results):
        self.results = results
        for category, items in results.items():
            cat = QTreeWidgetItem([category, human_size(sum(x.size for x in items)), "", ""])
            cat.setFlags(cat.flags() | Qt.ItemIsTristate | Qt.ItemIsUserCheckable)
            cat.setCheckState(0, Qt.Unchecked)
            self.tree.addTopLevelItem(cat)
            for item in items:
                child = QTreeWidgetItem([item.path, human_size(item.size), item.safety, item.note])
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Unchecked)
                cat.addChild(child)

        self.recalc()
        QMessageBox.information(
            self,
            "Сканирование завершено",
            "Файлы найдены. Теперь выберите нужные элементы и нажмите 'Удалить выбранное'.\n"
            "Рекомендуется начать с кнопки 'Выбрать безопасное'.",
        )

    def set_all(self, state):
        for i in range(self.tree.topLevelItemCount()):
            cat = self.tree.topLevelItem(i)
            cat.setCheckState(0, state)
        self.recalc()

    def select_safe(self):
        for i in range(self.tree.topLevelItemCount()):
            cat = self.tree.topLevelItem(i)
            for j in range(cat.childCount()):
                ch = cat.child(j)
                ch.setCheckState(0, Qt.Checked if ch.text(2) == "safe" else Qt.Unchecked)
        self.recalc()

    def selected_items(self):
        selected = []
        for i in range(self.tree.topLevelItemCount()):
            cat = self.tree.topLevelItem(i)
            for j in range(cat.childCount()):
                ch = cat.child(j)
                if ch.checkState(0) == Qt.Checked:
                    selected.append(ch)
        return selected

    def selected_paths_and_size(self):
        paths = []
        size = 0
        for ch in self.selected_items():
            paths.append(ch.text(0))
            val, unit = ch.text(1).split()
            mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}.get(unit, 1)
            size += int(float(val) * mult)
        return paths, size

    def recalc(self):
        _, size = self.selected_paths_and_size()
        self.total_label.setText(f"Выбрано: {human_size(size)}")

    def delete_selected(self):
        selected = self.selected_items()
        paths, size = self.selected_paths_and_size()
        if not paths:
            QMessageBox.information(self, "Нечего удалять", "Сначала отметьте файлы для удаления.")
            return

        preview = "\n".join(paths[:20])
        if len(paths) > 20:
            preview += f"\n... и ещё {len(paths) - 20}"

        msg = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Выбрано: {len(paths)} файлов ({human_size(size)})\n\n{preview}\n\nПродолжить?",
        )
        if msg != QMessageBox.Yes:
            return

        deleted, failed = self.cleaner.delete_files(paths, quarantine=self.quarantine_box.isChecked())

        # убираем удаленные элементы из списка
        for item in selected:
            if item.text(0) in deleted:
                parent = item.parent()
                if parent:
                    parent.removeChild(item)

        self.recalc()
        QMessageBox.information(self, "Готово", f"Успешно: {len(deleted)}\nОшибок: {len(failed)}")

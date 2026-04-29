from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QProgressBar,
    QLabel,
)

from core.scanner import DiskScanner, Node
from core.utils import human_size


class DiskScanWorker(QThread):
    progress = pyqtSignal(str)
    finished_scan = pyqtSignal(object)

    def __init__(self, root: str):
        super().__init__()
        self.scanner = DiskScanner()
        self.root = root

    def run(self):
        tree = self.scanner.scan_tree(self.root, progress_cb=lambda p: self.progress.emit(p))
        self.finished_scan.emit(tree)

    def cancel(self):
        self.scanner.cancel()


class DiskMapTab(QWidget):
    def __init__(self, get_root):
        super().__init__()
        self.get_root = get_root
        self.current_node = None
        self.stack = []
        self.worker = None

        layout = QVBoxLayout(self)
        btn_row = QHBoxLayout()
        self.scan_btn = QPushButton("Сканировать")
        self.back_btn = QPushButton("Назад")
        self.cancel_btn = QPushButton("Отмена")
        self.path_label = QLabel("Путь: -")
        btn_row.addWidget(self.scan_btn)
        btn_row.addWidget(self.back_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.path_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Папка", "Размер", "Файлов"])

        layout.addLayout(btn_row)
        layout.addWidget(self.progress)
        layout.addWidget(self.tree)

        self.scan_btn.clicked.connect(self.scan)
        self.back_btn.clicked.connect(self.go_back)
        self.cancel_btn.clicked.connect(self.cancel)
        self.tree.itemDoubleClicked.connect(self.open_child)

    def scan(self):
        root = self.get_root()
        self.path_label.setText(f"Путь: {root}")
        self.progress.setVisible(True)
        self.worker = DiskScanWorker(root)
        self.worker.progress.connect(lambda _: None)
        self.worker.finished_scan.connect(self.on_done)
        self.worker.start()

    def on_done(self, node: Node):
        self.progress.setVisible(False)
        self.stack.clear()
        self.current_node = node
        self.render(node)

    def render(self, node: Node):
        self.tree.clear()
        if not node:
            return
        self.path_label.setText(f"Путь: {node.path}")
        children = sorted(node.children.values(), key=lambda n: n.size, reverse=True)
        for ch in children:
            item = QTreeWidgetItem([ch.path.split("\\")[-1] or ch.path, human_size(ch.size), str(ch.files)])
            item.setData(0, 1, ch)
            self.tree.addTopLevelItem(item)

    def open_child(self, item, _):
        node = item.data(0, 1)
        if node:
            self.stack.append(self.current_node)
            self.current_node = node
            self.render(node)

    def go_back(self):
        if self.stack:
            self.current_node = self.stack.pop()
            self.render(self.current_node)

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()

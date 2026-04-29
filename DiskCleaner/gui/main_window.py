import os
from collections import Counter
from pathlib import Path

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import SETTINGS_FILE
from core.utils import disk_usage, human_size, iter_files, load_json, save_json
from gui.disk_map_tab import DiskMapTab
from gui.duplicates_tab import DuplicatesTab
from gui.junk_tab import JunkTab
from gui.large_files_tab import LargeFilesTab
from gui.old_files_tab import OldFilesTab


class DiskPieCanvas(FigureCanvas):
    def __init__(self):
        fig = Figure(figsize=(3, 3), facecolor="#1f232b")
        self.ax = fig.add_subplot(111)
        self.ax.set_facecolor("#1f232b")
        super().__init__(fig)

    def update_chart(self, used: int, free: int):
        self.ax.clear()
        self.ax.pie(
            [used, free],
            labels=["Занято", "Свободно"],
            colors=["#2d6cdf", "#3cb371"],
            autopct="%1.1f%%",
            textprops={"color": "#e6e9ef", "fontsize": 10},
        )
        self.draw()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DiskCleaner — анализ и очистка диска")
        self.resize(1450, 900)
        self.settings = load_json(SETTINGS_FILE, default={})

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        self.tabs = QTabWidget()
        self.disk_map_tab = DiskMapTab(self.current_drive)
        self.junk_tab = JunkTab(self.current_drive)
        self.large_tab = LargeFilesTab(self.current_drive)
        self.dupe_tab = DuplicatesTab(self.current_drive)
        self.old_tab = OldFilesTab(self.current_drive)

        self.tabs.addTab(self.disk_map_tab, "🗺 Карта диска")
        self.tabs.addTab(self.junk_tab, "🧹 Поиск мусора")
        self.tabs.addTab(self.large_tab, "📦 Большие файлы")
        self.tabs.addTab(self.dupe_tab, "🧬 Дубликаты")
        self.tabs.addTab(self.old_tab, "🕒 Старые файлы")

        sidebar = QWidget()
        side_layout = QVBoxLayout(sidebar)
        side_layout.setSpacing(10)

        drive_box_group = QGroupBox("Диск")
        drive_box_layout = QVBoxLayout(drive_box_group)
        self.drive_box = QComboBox()
        self.drive_box.addItems(self._available_drives())
        self.drive_box.setCurrentText(self.settings.get("drive", self.drive_box.currentText()))
        self.drive_box.currentTextChanged.connect(self.on_drive_changed)
        drive_box_layout.addWidget(QLabel("Выберите диск для анализа:"))
        drive_box_layout.addWidget(self.drive_box)

        usage_group = QGroupBox("Состояние диска")
        usage_layout = QVBoxLayout(usage_group)
        self.disk_label = QLabel("Информация о диске")
        self.pie = DiskPieCanvas()
        usage_layout.addWidget(self.disk_label)
        usage_layout.addWidget(self.pie)

        actions_group = QGroupBox("Дополнительные инструменты")
        actions_layout = QVBoxLayout(actions_group)
        self.ext_btn = QPushButton("Анализ расширений")
        self.empty_btn = QPushButton("Найти пустые папки")
        self.report_txt_btn = QPushButton("Экспорт TXT")
        self.report_html_btn = QPushButton("Экспорт HTML")
        self.ext_output = QLabel("-")
        self.ext_output.setWordWrap(True)

        actions_layout.addWidget(self.ext_btn)
        actions_layout.addWidget(self.empty_btn)
        actions_layout.addWidget(self.report_txt_btn)
        actions_layout.addWidget(self.report_html_btn)
        actions_layout.addWidget(self.ext_output)

        side_layout.addWidget(drive_box_group)
        side_layout.addWidget(usage_group)
        side_layout.addWidget(actions_group)
        side_layout.addStretch(1)

        splitter.addWidget(self.tabs)
        splitter.addWidget(sidebar)
        splitter.setSizes([1030, 390])

        self.setStatusBar(QStatusBar())

        self.ext_btn.clicked.connect(self.analyze_extensions)
        self.empty_btn.clicked.connect(self.find_empty_dirs)
        self.report_txt_btn.clicked.connect(lambda: self.export_report("txt"))
        self.report_html_btn.clicked.connect(lambda: self.export_report("html"))

        self.refresh_disk_info()

    def _available_drives(self):
        if os.name != "nt":
            return [str(Path.home())]
        drives = []
        for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            d = f"{c}:\\"
            if os.path.exists(d):
                drives.append(d)
        return drives or ["C:\\"]

    def current_drive(self):
        return self.drive_box.currentText()

    def on_drive_changed(self, drive):
        self.settings["drive"] = drive
        save_json(SETTINGS_FILE, self.settings)
        self.refresh_disk_info()

    def refresh_disk_info(self):
        usage = disk_usage(self.current_drive())
        if not usage:
            self.disk_label.setText("Нет доступа к диску")
            return
        self.disk_label.setText(
            f"Всего: {human_size(usage.total)}\nЗанято: {human_size(usage.used)}\nСвободно: {human_size(usage.free)}"
        )
        self.pie.update_chart(usage.used, usage.free)

    def analyze_extensions(self):
        counts = Counter()
        sizes = Counter()
        root = self.current_drive()
        limit = 15000
        for idx, path in enumerate(iter_files(root)):
            if idx > limit:
                break
            ext = os.path.splitext(path)[1].lower() or "(без расширения)"
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            counts[ext] += 1
            sizes[ext] += size
        top = sizes.most_common(10)
        text = "Топ расширений:\n" + "\n".join([f"{e}: {human_size(s)} ({counts[e]} файлов)" for e, s in top])
        self.ext_output.setText(text)

    def find_empty_dirs(self):
        root = self.current_drive()
        empties = []
        for current, dirs, files in os.walk(root):
            try:
                if not dirs and not files:
                    empties.append(current)
            except PermissionError:
                continue
            if len(empties) >= 200:
                break
        QMessageBox.information(self, "Пустые папки", "\n".join(empties[:100]) if empties else "Не найдено")

    def export_report(self, kind: str):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить отчет", f"report.{kind}", f"*.{kind}")
        if not path:
            return
        usage = disk_usage(self.current_drive())
        text = [
            "DiskCleaner report",
            f"Drive: {self.current_drive()}",
            f"Total: {human_size(usage.total) if usage else 'N/A'}",
            f"Used: {human_size(usage.used) if usage else 'N/A'}",
            f"Free: {human_size(usage.free) if usage else 'N/A'}",
            f"Junk categories found: {len(getattr(self.junk_tab, 'results', {}))}",
        ]
        if kind == "txt":
            Path(path).write_text("\n".join(text), encoding="utf-8")
        else:
            html = "<html><body><h1>DiskCleaner report</h1>" + "".join(f"<p>{line}</p>" for line in text) + "</body></html>"
            Path(path).write_text(html, encoding="utf-8")
        QMessageBox.information(self, "Готово", f"Отчёт сохранен: {path}")

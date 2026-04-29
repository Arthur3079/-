from __future__ import annotations

from pathlib import Path

from PyQt6.QtCharts import QChart, QChartView, QPieSeries
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.admin_access import admin_hint_message, has_admin_rights, inaccessible_system_paths
from core.empty_folders import find_empty_folders
from core.extension_analysis import aggregate_extensions


class MainWindow(QMainWindow):
    """Главное окно с анализом расширений и инструментом пустых папок."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Disk Cleaner")

        tabs = QTabWidget()
        tabs.addTab(self._build_extensions_tab(), "Расширения")
        tabs.addTab(self._build_empty_folders_tab(), "Пустые папки")

        self.setCentralWidget(tabs)
        self._show_admin_access_status()

    def _build_extensions_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)

        self.extensions_table = QTableWidget(0, 2)
        self.extensions_table.setHorizontalHeaderLabels(["Расширение", "Размер (байт)"])
        self.extensions_table.horizontalHeader().setStretchLastSection(True)

        self.extensions_chart = QChartView(QChart())
        self.extensions_chart.chart().setTitle("Распределение по расширениям")
        self.extensions_chart.setRenderHint(self.extensions_chart.renderHints())

        layout.addWidget(self.extensions_table, 2)
        layout.addWidget(self.extensions_chart, 3)
        return widget

    def _build_empty_folders_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.empty_folders_table = QTableWidget(0, 1)
        self.empty_folders_table.setHorizontalHeaderLabels(["Пустая папка"])
        self.empty_folders_table.horizontalHeader().setStretchLastSection(True)

        helper = QLabel("Отдельный инструмент поиска пустых папок.")
        helper.setStyleSheet("color: gray")
        layout.addWidget(helper)
        layout.addWidget(self.empty_folders_table)
        return widget

    def update_extension_view(self, paths_with_sizes: dict[Path, int]) -> None:
        totals = aggregate_extensions(paths_with_sizes)
        self.extensions_table.setRowCount(len(totals))

        series = QPieSeries()
        for row, (ext, size) in enumerate(totals.items()):
            self.extensions_table.setItem(row, 0, QTableWidgetItem(ext))
            self.extensions_table.setItem(row, 1, QTableWidgetItem(str(size)))
            series.append(ext, float(size))

        chart = QChart()
        chart.addSeries(series)
        chart.setTitle("Размер файлов по расширениям")
        self.extensions_chart.setChart(chart)

    def scan_empty_folders(self, root: Path) -> None:
        empty_folders = find_empty_folders(root)
        self.empty_folders_table.setRowCount(len(empty_folders))
        for row, folder in enumerate(empty_folders):
            self.empty_folders_table.setItem(row, 0, QTableWidgetItem(str(folder)))

    def _show_admin_access_status(self) -> None:
        if has_admin_rights():
            return

        system_paths = [Path("/root"), Path("/etc"), Path("/var/log")]
        blocked = inaccessible_system_paths(system_paths)
        if blocked:
            tooltip = "\n".join(str(path) for path in blocked)
            QMessageBox.information(
                self,
                "Ограниченный доступ",
                f"{admin_hint_message()}\n\nНедоступные пути:\n{tooltip}",
                QMessageBox.StandardButton.Ok,
            )

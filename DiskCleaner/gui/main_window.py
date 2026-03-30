"""Main window composition for DiskCleaner."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QWidget,
)

from config import APP_NAME, DEFAULT_DRIVE
from DiskCleaner.gui.disk_map_tab import DiskMapTab
from DiskCleaner.gui.duplicates_tab import DuplicatesTab
from DiskCleaner.gui.junk_tab import JunkTab
from DiskCleaner.gui.large_files_tab import LargeFilesTab
from DiskCleaner.gui.old_files_tab import OldFilesTab


class MainWindow(QMainWindow):
    """Application shell with tabs, drive selector, and summary state."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 760)

        self.drive_selector = QComboBox()
        self.drive_selector.addItems([DEFAULT_DRIVE, "D:/", "E:/"])

        self.summary_label = QLabel("Used: -- | Free: --")
        self.summary_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._build_toolbar()
        self._build_tabs()
        self._build_status_bar()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Controls")
        toolbar.setMovable(False)
        toolbar.addWidget(QLabel("Drive:"))
        toolbar.addWidget(self.drive_selector)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addWidget(self.summary_label)

        self.addToolBar(Qt.TopToolBarArea, toolbar)

    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.addTab(DiskMapTab(), "Disk Map")
        self.tabs.addTab(JunkTab(), "Junk Scanner")
        self.tabs.addTab(LargeFilesTab(), "Large Files")
        self.tabs.addTab(DuplicatesTab(), "Duplicates")
        self.tabs.addTab(OldFilesTab(), "Old Files")

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.addWidget(self.tabs)
        self.setCentralWidget(container)

    def _build_status_bar(self) -> None:
        status = QStatusBar()
        status.showMessage("Ready")
        status.addPermanentWidget(QLabel("Select drive and start scan."))
        self.setStatusBar(status)

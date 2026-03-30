"""Large files tab."""

from PyQt5.QtWidgets import QVBoxLayout, QWidget

from DiskCleaner.gui.widgets import PlaceholderPanel


class LargeFilesTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(
            PlaceholderPanel(
                "Large Files",
                "Review files exceeding your size threshold.",
            )
        )

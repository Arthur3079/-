"""Disk map tab."""

from PyQt5.QtWidgets import QVBoxLayout, QWidget

from DiskCleaner.gui.widgets import PlaceholderPanel


class DiskMapTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(
            PlaceholderPanel(
                "Disk Map",
                "This tab will show top folders by size and a simple usage map.",
            )
        )

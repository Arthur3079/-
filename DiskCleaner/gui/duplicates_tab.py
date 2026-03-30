"""Duplicate files tab."""

from PyQt5.QtWidgets import QVBoxLayout, QWidget

from DiskCleaner.gui.widgets import PlaceholderPanel


class DuplicatesTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(
            PlaceholderPanel(
                "Duplicates",
                "Inspect groups of duplicate files by content hash.",
            )
        )

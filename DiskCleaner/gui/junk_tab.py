"""Junk scanner tab."""

from PyQt5.QtWidgets import QVBoxLayout, QWidget

from DiskCleaner.gui.widgets import PlaceholderPanel


class JunkTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(
            PlaceholderPanel(
                "Junk Scanner",
                "Scan for temporary, log, and cache artifacts ready for cleanup.",
            )
        )

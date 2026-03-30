"""Old files tab."""

from PyQt5.QtWidgets import QVBoxLayout, QWidget

from DiskCleaner.gui.widgets import PlaceholderPanel


class OldFilesTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(
            PlaceholderPanel(
                "Old Files",
                "Find files not modified for a long time.",
            )
        )

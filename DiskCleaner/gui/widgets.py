"""Reusable widgets for tabs."""

from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderPanel(QWidget):
    """Simple placeholder content panel."""

    def __init__(self, title: str, message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title_label = QLabel(f"<h2>{title}</h2>")
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(message_label)
        layout.addStretch()

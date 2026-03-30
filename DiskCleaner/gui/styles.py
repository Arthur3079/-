"""Styling helpers for DiskCleaner GUI."""

from PyQt5.QtWidgets import QApplication

DARK_STYLESHEET = """
QWidget {
    background-color: #1e1f22;
    color: #e6e6e6;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #333;
    background: #26282c;
}
QTabBar::tab {
    background: #2b2d31;
    color: #d5d5d5;
    border: 1px solid #3a3d42;
    padding: 8px 14px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #3a3d42;
    color: #ffffff;
}
QStatusBar {
    background: #232428;
    border-top: 1px solid #333;
}
QComboBox, QPushButton {
    background: #2b2d31;
    border: 1px solid #444;
    padding: 4px 8px;
}
"""


def apply_dark_theme(app: QApplication) -> None:
    """Apply built-in dark stylesheet."""
    app.setStyleSheet(DARK_STYLESHEET)

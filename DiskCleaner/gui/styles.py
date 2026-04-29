DARK_STYLESHEET = """
QWidget {
    background-color: #181a1f;
    color: #e6e9ef;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}

QMainWindow {
    background-color: #181a1f;
}

QTabWidget::pane {
    border: 1px solid #2c313c;
    border-radius: 8px;
    top: -1px;
    background: #1f232b;
}

QTabBar::tab {
    background: #252a34;
    color: #b8c0d4;
    border: 1px solid #323846;
    border-bottom: none;
    padding: 8px 14px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}

QTabBar::tab:selected {
    background: #2f3645;
    color: #ffffff;
}

QGroupBox {
    border: 1px solid #2c313c;
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 10px;
    background-color: #1f232b;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #a9b4cc;
}

QHeaderView::section {
    background: #2a3140;
    color: #d8deee;
    padding: 6px;
    border: 1px solid #353d4d;
}

QTableWidget, QTreeWidget {
    gridline-color: #323846;
    background: #212733;
    alternate-background-color: #1b2029;
    border: 1px solid #2f3645;
    border-radius: 8px;
}

QTableWidget::item:selected, QTreeWidget::item:selected {
    background: #2d6cdf;
    color: #ffffff;
}

QPushButton {
    background: #2d6cdf;
    border: none;
    padding: 7px 12px;
    border-radius: 7px;
    color: white;
    font-weight: 600;
}

QPushButton:hover {
    background: #3a7bf0;
}

QPushButton:pressed {
    background: #1f57bd;
}

QLineEdit, QSpinBox, QComboBox {
    background: #202634;
    border: 1px solid #384052;
    border-radius: 6px;
    padding: 4px 6px;
}

QProgressBar {
    border: 1px solid #384052;
    border-radius: 6px;
    text-align: center;
    background: #1a1f28;
}

QProgressBar::chunk {
    background-color: #2d6cdf;
    border-radius: 5px;
}

QStatusBar {
    background: #12151b;
    color: #9ba6bf;
}

QScrollBar:vertical {
    background: #1c2029;
    width: 11px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #3a4355;
    min-height: 25px;
    border-radius: 5px;
}
"""

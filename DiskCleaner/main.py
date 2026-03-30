import sys

from PyQt5.QtWidgets import QApplication

from core.utils import is_admin
from gui.main_window import MainWindow
from gui.styles import DARK_STYLESHEET


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLESHEET)
    window = MainWindow()
    window.statusBar().showMessage(
        "Запущено с правами администратора" if is_admin() else "Запущено без прав администратора: часть системных папок будет недоступна"
    )
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

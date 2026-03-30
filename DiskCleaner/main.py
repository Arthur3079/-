import sys

from PyQt5.QtWidgets import QApplication, QMessageBox

from core.app_logger import setup_logging, get_logger
from core.utils import is_admin, request_admin_relaunch
from gui.main_window import MainWindow
from gui.styles import DARK_STYLESHEET


def main():
    setup_logging()
    logger = get_logger("diskcleaner.main")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLESHEET)

    admin = is_admin()
    logger.info("Application start. admin=%s", admin)

    if not admin:
        answer = QMessageBox.question(
            None,
            "Требуются права администратора",
            "Для полного доступа к системным папкам нужны права администратора.\n"
            "Перезапустить приложение с правами администратора сейчас?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            logger.info("User agreed to relaunch as administrator")
            if request_admin_relaunch():
                logger.info("Relaunch request sent via UAC")
                return
            logger.warning("Relaunch as administrator failed")
            QMessageBox.warning(None, "Не удалось", "Не удалось запросить права администратора. Продолжаем без них.")
        else:
            logger.info("User declined administrator relaunch")

    window = MainWindow()
    window.statusBar().showMessage(
        "Запущено с правами администратора" if admin else "Запущено без прав администратора: часть системных папок будет недоступна"
    )
    window.show()
    exit_code = app.exec_()
    logger.info("Application exit. code=%s", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

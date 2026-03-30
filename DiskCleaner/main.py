"""Application entrypoint for DiskCleaner."""

import logging
import sys
import traceback
from pathlib import Path

from PyQt5.QtWidgets import QApplication, QMessageBox

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import APP_NAME, APP_VERSION, LOG_DIR, LOG_FILE
from DiskCleaner.gui.main_window import MainWindow
from DiskCleaner.gui.styles import apply_dark_theme


def configure_logging() -> None:
    """Setup basic file logging."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> int:
    """Run QApplication and main window with top-level exception handling."""
    configure_logging()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    apply_dark_theme(app)

    try:
        window = MainWindow()
        window.show()
        return app.exec_()
    except Exception as exc:  # top-level guard
        logging.exception("Unhandled exception in GUI startup")
        traceback.print_exc()
        QMessageBox.critical(
            None,
            "DiskCleaner Error",
            f"Unexpected error: {exc}\n\nSee logs for details: {LOG_FILE}",
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

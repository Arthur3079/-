import logging
from logging.handlers import RotatingFileHandler

from config import APP_LOG_FILE


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("diskcleaner")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    file_handler = RotatingFileHandler(APP_LOG_FILE, maxBytes=3 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.info("Logger initialized. Log file: %s", APP_LOG_FILE)
    return logger


def get_logger(name: str = "diskcleaner") -> logging.Logger:
    root = setup_logging()
    if name == "diskcleaner":
        return root
    return logging.getLogger(name)

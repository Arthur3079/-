"""Global configuration for DiskCleaner."""

from pathlib import Path

APP_NAME = "DiskCleaner"
APP_VERSION = "0.1.0"
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "DiskCleaner" / "logs"
LOG_FILE = LOG_DIR / "cleanup_log.txt"
DEFAULT_DRIVE = "C:/"
LARGE_FILE_THRESHOLD_MB = 512
OLD_FILE_THRESHOLD_DAYS = 365

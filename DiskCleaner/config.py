from pathlib import Path

APP_NAME = "DiskCleaner"
APP_VERSION = "1.0.0"

ROOT_DIR = Path(__file__).resolve().parent
LOG_DIR = ROOT_DIR / "logs"
LOG_FILE = LOG_DIR / "cleanup_log.txt"
CACHE_DIR = ROOT_DIR / ".cache"
QUARANTINE_DIR = ROOT_DIR / "quarantine"
SETTINGS_FILE = ROOT_DIR / "settings.json"

LOG_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

SAFE_LEVEL = "safe"
CAUTION_LEVEL = "caution"
DANGER_LEVEL = "danger"

DEFAULT_LARGE_FILE_MB = 100
DEFAULT_OLD_MONTHS = 12

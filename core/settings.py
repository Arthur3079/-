from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class UserPreferences:
    selected_categories: list[str]
    last_disk: str
    min_size_threshold_mb: int
    max_age_days: int
    deletion_mode: str


class SettingsManager:
    """Сохранение/загрузка пользовательских настроек через QSettings."""

    def __init__(self, organization: str = "DiskCleaner", application: str = "DiskCleanerApp") -> None:
        try:
            from PyQt6.QtCore import QSettings  # pylint: disable=import-outside-toplevel
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Для работы SettingsManager требуется PyQt6") from exc

        self._settings = QSettings(organization, application)

    def save_preferences(self, prefs: UserPreferences) -> None:
        self._settings.setValue("scan/selected_categories", prefs.selected_categories)
        self._settings.setValue("scan/last_disk", prefs.last_disk)
        self._settings.setValue("filters/min_size_threshold_mb", prefs.min_size_threshold_mb)
        self._settings.setValue("filters/max_age_days", prefs.max_age_days)
        self._settings.setValue("cleanup/deletion_mode", prefs.deletion_mode)
        self._settings.sync()

    def load_preferences(self) -> UserPreferences:
        selected_categories = self._settings.value("scan/selected_categories", [], type=list)
        last_disk = self._settings.value("scan/last_disk", "", type=str)
        min_size_threshold_mb = self._settings.value("filters/min_size_threshold_mb", 100, type=int)
        max_age_days = self._settings.value("filters/max_age_days", 30, type=int)
        deletion_mode = self._settings.value("cleanup/deletion_mode", "quarantine", type=str)
        return UserPreferences(
            selected_categories=selected_categories,
            last_disk=last_disk,
            min_size_threshold_mb=min_size_threshold_mb,
            max_age_days=max_age_days,
            deletion_mode=deletion_mode,
        )

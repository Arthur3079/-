import glob
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from config import CAUTION_LEVEL, DANGER_LEVEL, SAFE_LEVEL
from .utils import file_stat_safe, iter_files


@dataclass
class JunkItem:
    path: str
    size: int
    category: str
    safety: str
    note: str = ""


class JunkFinder:
    def __init__(self):
        self.cancel_requested = False

    def cancel(self):
        self.cancel_requested = True

    def _glob_files(self, pattern: str) -> List[str]:
        return [p for p in glob.glob(pattern, recursive=True) if os.path.isfile(p)]

    def _path_size(self, path: str) -> int:
        st = file_stat_safe(path)
        return st.st_size if st else 0

    def _add_patterns(self, out: List[JunkItem], category: str, safety: str, patterns: List[str], note: str = ""):
        for pattern in patterns:
            for path in self._glob_files(pattern):
                if self.cancel_requested:
                    return
                out.append(JunkItem(path=path, size=self._path_size(path), category=category, safety=safety, note=note))

    def scan(self, drive: str = "C:\\") -> Dict[str, List[JunkItem]]:
        self.cancel_requested = False
        user = os.environ.get("USERPROFILE", str(Path.home()))
        local = os.path.join(user, "AppData", "Local")
        roaming = os.path.join(user, "AppData", "Roaming")
        home = str(Path.home())

        result: Dict[str, List[JunkItem]] = {}

        def put(name: str, items: List[JunkItem]):
            result[name] = items

        # temp files
        temp = []
        self._add_patterns(temp, "Временные файлы", SAFE_LEVEL, [
            r"C:\\Windows\\Temp\\**\\*",
            os.path.join(local, "Temp", "**", "*"),
        ])
        for ext in ["*.tmp", "*.temp", "*.old", "*.bak", "*.dmp", "*.mdmp", "*.~*"]:
            for p in iter_files(user):
                if self.cancel_requested:
                    break
                if os.path.basename(p).lower().endswith(ext.replace("*", "").lower()):
                    temp.append(JunkItem(p, self._path_size(p), "Временные файлы", SAFE_LEVEL))
        put("Временные файлы", temp)

        browsers = []
        self._add_patterns(browsers, "Кэш браузеров", SAFE_LEVEL, [
            os.path.join(local, "Google", "Chrome", "User Data", "Default", "Cache", "**", "*"),
            os.path.join(local, "Mozilla", "Firefox", "Profiles", "*", "cache2", "**", "*"),
            os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Cache", "**", "*"),
            os.path.join(roaming, "Opera Software", "Opera Stable", "Cache", "**", "*"),
            os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data", "Default", "Cache", "**", "*"),
        ])
        put("Кэш браузеров", browsers)

        win_cache = []
        self._add_patterns(win_cache, "Кэш Windows", SAFE_LEVEL, [
            os.path.join(local, "IconCache.db"),
            r"C:\\Windows\\SoftwareDistribution\\Download\\**\\*",
        ])
        self._add_patterns(win_cache, "Кэш Windows", CAUTION_LEVEL, [r"C:\\Windows\\Prefetch\\**\\*"], note="Удалять с осторожностью")
        self._add_patterns(win_cache, "Кэш Windows", DANGER_LEVEL, [r"C:\\Windows\\System32\\FNTCACHE.DAT"], note="Только информация")
        put("Кэш Windows", win_cache)

        logs = []
        self._add_patterns(logs, "Логи", CAUTION_LEVEL, [
            os.path.join(user, "**", "*.log"),
            r"C:\\Windows\\Logs\\**\\*",
            r"C:\\Windows\\*.log",
        ])
        put("Логи", logs)

        thumbs = []
        self._add_patterns(thumbs, "Миниатюры", SAFE_LEVEL, [os.path.join(local, "Microsoft", "Windows", "Explorer", "thumbcache_*.db")])
        put("Миниатюры", thumbs)

        app_cache = []
        self._add_patterns(app_cache, "Кэш приложений", SAFE_LEVEL, [
            os.path.join(local, "Spotify", "Storage", "**", "*"),
            os.path.join(roaming, "discord", "Cache", "**", "*"),
            os.path.join(roaming, "Microsoft", "Teams", "Cache", "**", "*"),
            os.path.join(roaming, "Code", "Cache", "**", "*"),
            os.path.join(local, "pip", "cache", "**", "*"),
            os.path.join(roaming, "npm-cache", "**", "*"),
            os.path.join(home, ".gradle", "caches", "**", "*"),
            os.path.join(local, "NuGet", "Cache", "**", "*"),
            r"C:\\Program Files (x86)\\Steam\\appcache\\**\\*",
            r"C:\\Program Files\\Steam\\appcache\\**\\*",
        ])
        put("Кэш приложений", app_cache)

        updates = []
        self._add_patterns(updates, "Файлы обновлений", CAUTION_LEVEL, [r"C:\\Windows.old\\**\\*", r"C:\\$Windows.~BT\\**\\*", r"C:\\$Windows.~WS\\**\\*"])
        self._add_patterns(updates, "Файлы обновлений", DANGER_LEVEL, [r"C:\\Windows\\WinSxS\\**\\*", r"C:\\Windows\\Installer\\**\\*"], note="Только информация")
        put("Файлы обновлений", updates)

        dumps = []
        self._add_patterns(dumps, "Дампы памяти", SAFE_LEVEL, [r"C:\\Windows\\MEMORY.DMP", r"C:\\Windows\\Minidump\\**\\*", os.path.join(user, "**", "*.dmp"), os.path.join(user, "**", "*.mdmp")])
        put("Дампы памяти", dumps)

        shader = []
        self._add_patterns(shader, "Кэш DirectX Shader", SAFE_LEVEL, [
            os.path.join(local, "D3DSCache", "**", "*"),
            os.path.join(local, "NVIDIA", "DXCache", "**", "*"),
            os.path.join(local, "AMD", "DxCache", "**", "*"),
        ])
        put("Кэш DirectX Shader", shader)

        info_only = []
        for path in [r"C:\\hiberfil.sys", r"C:\\pagefile.sys", r"C:\\swapfile.sys"]:
            if os.path.exists(path):
                info_only.append(JunkItem(path, self._path_size(path), "Системные файлы", DANGER_LEVEL, note="Только информация"))
        put("Системные файлы", info_only)

        downloads = []
        self._add_patterns(downloads, "Загрузки и установщики", CAUTION_LEVEL, [os.path.join(user, "Downloads", "**", "*.exe"), os.path.join(user, "Downloads", "**", "*.msi")])
        put("Загрузки и установщики", downloads)

        return result

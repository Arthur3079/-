from __future__ import annotations

from pathlib import Path

from .reports import CleanupReport, export_report_html, export_report_txt


def export_cleanup_report(report: CleanupReport, output_path: Path, fmt: str) -> Path:
    """Экспортирует отчёт в заданный формат (TXT или HTML)."""

    normalized = fmt.strip().lower()
    if normalized == "txt":
        return export_report_txt(report, output_path)
    if normalized == "html":
        return export_report_html(report, output_path)
    raise ValueError(f"Неподдерживаемый формат отчёта: {fmt}")

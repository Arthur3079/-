from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class ReportCategory:
    """Секция отчёта: категория и найденные в ней элементы."""

    name: str
    items: list[Path] = field(default_factory=list)
    total_size_bytes: int = 0


@dataclass(slots=True)
class CleanupAction:
    """Информация о выбранном элементе и результате действия."""

    path: Path
    selected_for_delete: bool
    action: str
    success: bool
    details: str = ""


@dataclass(slots=True)
class CleanupReport:
    """Унифицированная модель для экспорта отчётов."""

    categories: list[ReportCategory] = field(default_factory=list)
    reclaimable_bytes: int = 0
    actions: list[CleanupAction] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.utcnow)


def _format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    current = float(max(value, 0))
    for unit in units:
        if current < 1024 or unit == units[-1]:
            return f"{current:.2f} {unit}"
        current /= 1024
    return f"{value} B"


def export_report_txt(report: CleanupReport, output_file: Path) -> Path:
    """Экспортирует отчёт в TXT."""

    lines: list[str] = []
    lines.append(f"Отчёт создан: {report.generated_at.isoformat()} UTC")
    lines.append("")
    lines.append("Найденные элементы по категориям")
    lines.append("=" * 40)

    for category in report.categories:
        lines.append(f"- {category.name}: {len(category.items)} шт., { _format_bytes(category.total_size_bytes)}")
        for item in category.items:
            lines.append(f"    • {item}")

    lines.append("")
    lines.append(f"Потенциально освобождаемый объём: {_format_bytes(report.reclaimable_bytes)}")
    lines.append("")
    lines.append("Выбранные к удалению и выполненные действия")
    lines.append("=" * 40)

    for action in report.actions:
        selected = "Да" if action.selected_for_delete else "Нет"
        status = "Успех" if action.success else "Ошибка"
        details = f" ({action.details})" if action.details else ""
        lines.append(
            f"- {action.path} | выбрано: {selected} | действие: {action.action} | статус: {status}{details}"
        )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(lines), encoding="utf-8")
    return output_file


def export_report_html(report: CleanupReport, output_file: Path) -> Path:
    """Экспортирует отчёт в HTML."""

    rows: list[str] = []
    for action in report.actions:
        selected = "Да" if action.selected_for_delete else "Нет"
        status = "Успех" if action.success else "Ошибка"
        rows.append(
            "<tr>"
            f"<td>{escape(str(action.path))}</td>"
            f"<td>{selected}</td>"
            f"<td>{escape(action.action)}</td>"
            f"<td>{status}</td>"
            f"<td>{escape(action.details)}</td>"
            "</tr>"
        )

    categories_html: list[str] = []
    for category in report.categories:
        category_items = "".join(f"<li>{escape(str(item))}</li>" for item in category.items)
        categories_html.append(
            "<section>"
            f"<h3>{escape(category.name)}</h3>"
            f"<p>Элементов: {len(category.items)}; размер: {_format_bytes(category.total_size_bytes)}</p>"
            f"<ul>{category_items}</ul>"
            "</section>"
        )

    html = f"""<!doctype html>
<html lang=\"ru\">
<head>
  <meta charset=\"utf-8\" />
  <title>Отчёт очистки диска</title>
  <style>
    body {{ font-family: sans-serif; margin: 24px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background: #f4f4f4; }}
    section {{ margin-bottom: 20px; }}
  </style>
</head>
<body>
  <h1>Отчёт очистки диска</h1>
  <p>Сформирован: {report.generated_at.isoformat()} UTC</p>
  <h2>Найденные элементы по категориям</h2>
  {''.join(categories_html)}
  <h2>Потенциально освобождаемый объём</h2>
  <p>{_format_bytes(report.reclaimable_bytes)}</p>
  <h2>Выбранные к удалению и выполненные действия</h2>
  <table>
    <thead><tr><th>Путь</th><th>Выбрано</th><th>Действие</th><th>Статус</th><th>Детали</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</body>
</html>
"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")
    return output_file


def build_report_categories(category_map: dict[str, Iterable[Path]], sizes: dict[Path, int]) -> list[ReportCategory]:
    """Строит категории отчёта из результатов сканирования."""

    report_categories: list[ReportCategory] = []
    for name, items in category_map.items():
        item_list = list(items)
        total = sum(sizes.get(item, 0) for item in item_list)
        report_categories.append(ReportCategory(name=name, items=item_list, total_size_bytes=total))
    return report_categories

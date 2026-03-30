from pathlib import Path

from core.empty_folders import find_empty_folders
from core.extension_analysis import aggregate_extensions
from core.reports import CleanupAction, CleanupReport, ReportCategory
from core.utils import export_cleanup_report


def test_aggregate_extensions() -> None:
    data = {
        Path("a.txt"): 100,
        Path("b.txt"): 300,
        Path("c.log"): 50,
        Path("d"): 25,
    }
    result = aggregate_extensions(data)
    assert result[".txt"] == 400
    assert result[".log"] == 50
    assert result["[без расширения]"] == 25


def test_find_empty_folders(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    non_empty = tmp_path / "non_empty"
    non_empty.mkdir()
    (non_empty / "file.txt").write_text("x", encoding="utf-8")

    found = find_empty_folders(tmp_path)
    assert empty in found
    assert non_empty not in found


def test_report_export_txt_and_html(tmp_path: Path) -> None:
    report = CleanupReport(
        categories=[ReportCategory(name="Temp", items=[Path("/tmp/a.tmp")], total_size_bytes=1024)],
        reclaimable_bytes=1024,
        actions=[CleanupAction(path=Path("/tmp/a.tmp"), selected_for_delete=True, action="delete", success=True)],
    )

    txt_path = export_cleanup_report(report, tmp_path / "report.txt", "txt")
    html_path = export_cleanup_report(report, tmp_path / "report.html", "html")

    assert txt_path.exists()
    assert "Потенциально освобождаемый объём" in txt_path.read_text(encoding="utf-8")
    assert html_path.exists()
    assert "<html" in html_path.read_text(encoding="utf-8")

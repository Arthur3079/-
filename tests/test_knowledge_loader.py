"""Tests for sonya.knowledge.loader."""

from __future__ import annotations

from pathlib import Path

from sonya.knowledge.loader import load_chunks


def _write(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8")


def test_loads_simple_file(tmp_path: Path) -> None:
    _write(
        tmp_path / "01_persona.md",
        "# Persona\n\nThis is the persona body. " * 10 + "\n\n## Voice\n\nVoice notes here. " * 5,
    )
    chunks, stats = load_chunks(tmp_path)
    assert stats.files_indexed == 1
    assert len(chunks) >= 1
    file_ids = {c.file_id for c in chunks}
    assert file_ids == {"01_persona"}


def test_handles_empty_dir(tmp_path: Path) -> None:
    chunks, stats = load_chunks(tmp_path)
    assert chunks == []
    assert stats.files_indexed == 0


def test_skips_non_markdown(tmp_path: Path) -> None:
    _write(tmp_path / "data.jsonl", '{"x": 1}\n')
    _write(tmp_path / "x.py", "print('hi')\n")
    _write(
        tmp_path / "01.md",
        "# Title\n\n" + ("Some content paragraph.\n\n" * 5),
    )
    chunks, stats = load_chunks(tmp_path)
    assert stats.files_scanned == 1
    assert all(c.file_id == "01" for c in chunks)


def test_tags_derived_from_filename_and_heading(tmp_path: Path) -> None:
    (tmp_path / "ai_training").mkdir(exist_ok=True)
    _write(
        tmp_path / "ai_training" / "09_welcome_flow_playbook.md",
        "# Welcome Flow\n\n" + ("Some welcome content for new fans. " * 10),
    )
    chunks, _ = load_chunks(tmp_path)
    assert chunks
    tags = chunks[0].tags
    assert "welcome" in tags
    assert "flow" in tags
    assert "playbook" in tags  # derived from ai_training path or filename


def test_oversized_section_is_split(tmp_path: Path) -> None:
    big = "Lorem ipsum dolor sit amet, " * 400  # ~10KB
    _write(
        tmp_path / "long.md",
        f"# Big section\n\n{big}\n\n{big}\n",
    )
    chunks, _ = load_chunks(tmp_path)
    # All chunks must be under the hard ceiling.
    assert all(c.char_count <= 1500 for c in chunks)
    assert len(chunks) >= 2


def test_tiny_sections_merged(tmp_path: Path) -> None:
    _write(
        tmp_path / "small.md",
        "# A\n\nx\n\n# B\n\ny\n\n# C\n\n"
        + "Real content here that's longer than the merge threshold. " * 5,
    )
    chunks, _ = load_chunks(tmp_path)
    # The two tiny prefix sections must not produce 3 separate chunks.
    assert len(chunks) <= 2

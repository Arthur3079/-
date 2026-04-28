"""Markdown loader: walks `knowledge/`, splits each .md into section chunks.

Chunking strategy:
- Each markdown file is split on top-level H1/H2 headings (`# ` / `## `).
- Sections smaller than `MIN_CHUNK_CHARS` are merged into the previous chunk
  so we don't get a snippet that's just a heading.
- Sections larger than `MAX_CHUNK_CHARS` are split on H3 (`### `) boundaries;
  if still oversized, they're hard-split on paragraph boundaries.
- Tags are derived heuristically from the filename and from words present in
  the section heading (e.g. `09_welcome_flow_playbook.md` → tags
  {"welcome", "playbook", "flow"}). This is enough for keyword retrieval.

We deliberately ignore non-markdown files (e.g. `*.jsonl`, `_generate_*.py`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MIN_CHUNK_CHARS = 80
MAX_CHUNK_CHARS = 1400


@dataclass(frozen=True)
class KnowledgeChunk:
    file_id: str
    """Stable id like `ai_training/06_AI_stop_list` (relative path, no ext)."""

    section: str
    """Section heading, e.g. "A. Юридические запреты"; "" for file-level chunk."""

    text: str
    """Section body, with the heading line included for context."""

    tags: frozenset[str] = field(default_factory=frozenset)
    """Lowercase tag tokens derived from filename + heading."""

    char_count: int = 0


@dataclass(frozen=True)
class KnowledgeStats:
    files_scanned: int
    files_indexed: int
    chunks: int
    total_chars: int


_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
_NON_WORD_RE = re.compile(r"[^a-z0-9а-яё]+")
_TAG_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "this", "that", "from", "into", "your",
        "you", "are", "not", "but", "all", "can", "any", "how",
        "ai", "md", "of", "on", "to", "in", "is", "it", "an", "a",
        "и", "не", "по", "на", "в", "с", "к", "о", "у", "за",
        "playbook", "examples", "training",
    }
)


def load_chunks(knowledge_dir: Path) -> tuple[list[KnowledgeChunk], KnowledgeStats]:
    """Walk `knowledge_dir`, return (chunks, stats).

    Stable order: files sorted by relative path; within a file, sections
    sorted by occurrence.
    """
    chunks: list[KnowledgeChunk] = []
    files_scanned = 0
    files_indexed = 0
    total_chars = 0

    if not knowledge_dir.exists():
        return chunks, KnowledgeStats(0, 0, 0, 0)

    md_files = sorted(p for p in knowledge_dir.rglob("*.md") if p.is_file())

    for path in md_files:
        files_scanned += 1
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not content.strip():
            continue

        rel = path.relative_to(knowledge_dir).with_suffix("")
        file_id = rel.as_posix()
        file_tags = _tags_from_filename(file_id)

        for chunk in _split_into_sections(content):
            section, body = chunk
            if not body.strip():
                continue
            section_tags = _tags_from_heading(section)
            tags = file_tags | section_tags
            kc = KnowledgeChunk(
                file_id=file_id,
                section=section,
                text=body,
                tags=frozenset(tags),
                char_count=len(body),
            )
            chunks.append(kc)
            total_chars += kc.char_count

        files_indexed += 1

    return chunks, KnowledgeStats(
        files_scanned=files_scanned,
        files_indexed=files_indexed,
        chunks=len(chunks),
        total_chars=total_chars,
    )


def _split_into_sections(content: str) -> list[tuple[str, str]]:
    """Return list of (section_heading, section_body) tuples.

    `section_body` includes the heading line so the LLM gets context.
    """
    matches = list(_HEADING_RE.finditer(content))
    if not matches:
        return _hard_split("", content)

    sections: list[tuple[str, str]] = []
    # Pre-section preamble (rare but exists).
    if matches[0].start() > 0:
        preamble = content[: matches[0].start()].strip()
        if preamble:
            sections.append(("", preamble))

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        title = m.group(2).strip()
        sections.append((title, body))

    # Merge tiny sections forward.
    merged: list[tuple[str, str]] = []
    buffer_title = ""
    buffer_body = ""
    for title, body in sections:
        if len(body) < MIN_CHUNK_CHARS:
            if buffer_body:
                buffer_body = f"{buffer_body}\n\n{body}"
            else:
                buffer_title, buffer_body = title, body
            continue
        if buffer_body:
            merged.append((buffer_title, f"{buffer_body}\n\n{body}"))
            buffer_title, buffer_body = "", ""
        else:
            merged.append((title, body))
    if buffer_body:
        merged.append((buffer_title, buffer_body))

    # Hard-split anything still oversized.
    out: list[tuple[str, str]] = []
    for title, body in merged:
        if len(body) <= MAX_CHUNK_CHARS:
            out.append((title, body))
        else:
            out.extend(_hard_split(title, body))
    return out


def _hard_split(title: str, body: str) -> list[tuple[str, str]]:
    """Split an oversized section on blank lines, respecting MAX_CHUNK_CHARS.

    If a single paragraph itself exceeds the cap, it gets brute-split on
    sentence boundaries / character runs as a last resort.
    """
    paragraphs: list[str] = []
    for raw in body.split("\n\n"):
        p = raw.strip()
        if not p:
            continue
        if len(p) <= MAX_CHUNK_CHARS:
            paragraphs.append(p)
        else:
            paragraphs.extend(_split_long_paragraph(p))

    out: list[tuple[str, str]] = []
    buf: list[str] = []
    size = 0
    for p in paragraphs:
        plen = len(p) + 2
        if size + plen > MAX_CHUNK_CHARS and buf:
            out.append((title, "\n\n".join(buf)))
            buf = [p]
            size = plen
        else:
            buf.append(p)
            size += plen
    if buf:
        out.append((title, "\n\n".join(buf)))
    return out


def _split_long_paragraph(p: str) -> list[str]:
    """Split a single oversized paragraph on sentence boundaries, then by chars."""
    # Try sentence-ish boundaries first.
    sentences = re.split(r"(?<=[.!?])\s+", p)
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for s in sentences:
        if not s:
            continue
        slen = len(s) + 1
        if size + slen > MAX_CHUNK_CHARS and buf:
            parts.append(" ".join(buf))
            buf = [s]
            size = slen
        else:
            buf.append(s)
            size += slen
    if buf:
        parts.append(" ".join(buf))
    # Some "sentences" can still be huge (no punctuation at all).
    final: list[str] = []
    for part in parts:
        if len(part) <= MAX_CHUNK_CHARS:
            final.append(part)
        else:
            for i in range(0, len(part), MAX_CHUNK_CHARS):
                final.append(part[i : i + MAX_CHUNK_CHARS])
    return final


def _tags_from_filename(file_id: str) -> set[str]:
    """`ai_training/09_welcome_flow_playbook` → {welcome, flow, playbook, ai_training}."""
    parts = file_id.lower().split("/")
    tokens: set[str] = set()
    for part in parts:
        for raw in re.split(r"[^a-z0-9а-яё]+", part):
            if not raw or raw.isdigit():
                continue
            if raw in _TAG_STOPWORDS:
                continue
            if len(raw) < 3:
                continue
            tokens.add(raw)
    if "ai_training" in file_id:
        tokens.add("playbook")
    return tokens


def _tags_from_heading(heading: str) -> set[str]:
    if not heading:
        return set()
    tokens: set[str] = set()
    for raw in _NON_WORD_RE.split(heading.lower()):
        if not raw or raw.isdigit():
            continue
        if raw in _TAG_STOPWORDS:
            continue
        if len(raw) < 3:
            continue
        tokens.add(raw)
    return tokens

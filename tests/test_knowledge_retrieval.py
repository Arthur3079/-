"""Tests for sonya.knowledge.retrieval (KnowledgeIndex)."""

from __future__ import annotations

from sonya.knowledge.loader import KnowledgeChunk
from sonya.knowledge.retrieval import KnowledgeIndex


def _chunk(file_id: str, section: str, text: str, tags: set[str]) -> KnowledgeChunk:
    return KnowledgeChunk(
        file_id=file_id,
        section=section,
        text=text,
        tags=frozenset(tags),
        char_count=len(text),
    )


def test_empty_index_returns_empty() -> None:
    idx = KnowledgeIndex([])
    assert idx.retrieve("anything") == []


def test_retrieves_by_keyword_overlap() -> None:
    idx = KnowledgeIndex(
        [
            _chunk(
                "welcome",
                "Welcome flow",
                "Greet the fan warmly when they arrive for the first time.",
                {"welcome", "playbook"},
            ),
            _chunk(
                "ghost",
                "Ghost recovery",
                "If a fan has gone silent for 7 days, send a soft re-engagement.",
                {"ghost", "recovery", "playbook"},
            ),
        ]
    )
    out = idx.retrieve("how do I do welcome flow with a new fan?")
    assert out
    assert out[0].file_id == "welcome"


def test_respects_max_chunks() -> None:
    chunks = [_chunk(f"file_{i}", "T", f"keyword_{i} " * 20, {"keyword"}) for i in range(10)]
    idx = KnowledgeIndex(chunks)
    out = idx.retrieve("keyword", max_chunks=3, max_chars=10_000)
    assert len(out) <= 3


def test_respects_max_chars() -> None:
    chunks = [_chunk(f"f{i}", "T", "word " * 100, {"word"}) for i in range(5)]
    idx = KnowledgeIndex(chunks)
    out = idx.retrieve("word", max_chunks=10, max_chars=300)
    total = sum(len(s.text) for s in out)
    # We allow the first chunk to exceed budget (always include at least one),
    # but subsequent ones must fit.
    assert total <= 700  # one ~500-char chunk; second one would exceed budget


def test_fan_type_and_intent_boost() -> None:
    idx = KnowledgeIndex(
        [
            _chunk("a", "general", "neutral content", {"general"}),
            _chunk("b", "whales", "high-value fan playbook", {"whale", "playbook"}),
        ]
    )
    out = idx.retrieve("playbook", fan_type="whale")
    assert out
    assert out[0].file_id == "b"


def test_no_overlap_returns_empty() -> None:
    idx = KnowledgeIndex([_chunk("x", "T", "lorem ipsum dolor", {"lorem"})])
    out = idx.retrieve("zxyqq nothing matches here either")
    assert out == []

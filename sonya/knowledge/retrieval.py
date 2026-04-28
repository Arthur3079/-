"""Lightweight in-process retrieval over `KnowledgeChunk`s.

Scoring: token overlap between the query and the chunk's tag/text tokens,
with a small boost when explicit `fan_type` / `intent` arguments match a
chunk tag. We cap output by both `max_chunks` and `max_chars` so we never
blow the prompt budget.

This is intentionally not embeddings — for ~150 chunks of <2 KB each, naive
in-memory keyword matching is fast (<1 ms) and trivial to reason about.
When the corpus grows or recall becomes the bottleneck, swap the scorer
without changing the public API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sonya.knowledge.loader import KnowledgeChunk

_TOKEN_RE = re.compile(r"[a-z0-9а-яё]+", re.IGNORECASE)


@dataclass(frozen=True)
class RetrievedSnippet:
    file_id: str
    section: str
    text: str
    score: float


class KnowledgeIndex:
    """Holds chunks and a per-chunk lazy token cache."""

    def __init__(self, chunks: list[KnowledgeChunk]) -> None:
        self._chunks = list(chunks)
        # Pre-compute lower-cased token sets to avoid re-tokenising per query.
        self._tokens: list[frozenset[str]] = [
            _tokenise(c.text) | {t.lower() for t in c.tags} for c in self._chunks
        ]

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def chunks(self) -> list[KnowledgeChunk]:
        return list(self._chunks)

    def retrieve(
        self,
        query: str,
        *,
        max_chunks: int = 4,
        max_chars: int = 1800,
        fan_type: str | None = None,
        intent: str | None = None,
    ) -> list[RetrievedSnippet]:
        """Return up to `max_chunks` snippets, total length <= `max_chars`.

        If the query is empty / too short to score, returns []. We do **not**
        return arbitrary popular chunks — silence is better than noise.
        """
        if not self._chunks:
            return []
        q_tokens = _tokenise(query)
        if fan_type:
            q_tokens = q_tokens | {fan_type.lower()}
        if intent:
            q_tokens = q_tokens | {intent.lower()}
        if not q_tokens:
            return []

        scored: list[tuple[float, int]] = []
        for i, c in enumerate(self._chunks):
            chunk_tokens = self._tokens[i]
            if not chunk_tokens:
                continue
            overlap = q_tokens & chunk_tokens
            if not overlap:
                continue
            base = len(overlap)
            # Heading tokens get a boost: the more general the section title,
            # the more discriminating an overlap there is.
            heading_tokens = _tokenise(c.section)
            heading_boost = 1.5 * len(q_tokens & heading_tokens)
            tag_boost = 0.0
            if fan_type and fan_type.lower() in c.tags:
                tag_boost += 1.0
            if intent and intent.lower() in c.tags:
                tag_boost += 1.0
            # Normalise by chunk length so long files don't always win.
            length_norm = max(1.0, c.char_count / 600.0)
            score = (base + heading_boost + tag_boost) / length_norm
            if score > 0:
                scored.append((score, i))

        if not scored:
            return []

        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[RetrievedSnippet] = []
        used = 0
        for score, idx in scored:
            chunk = self._chunks[idx]
            if used + chunk.char_count > max_chars and out:
                break
            out.append(
                RetrievedSnippet(
                    file_id=chunk.file_id,
                    section=chunk.section,
                    text=chunk.text,
                    score=score,
                )
            )
            used += chunk.char_count
            if len(out) >= max_chunks:
                break
        return out


def _tokenise(text: str) -> frozenset[str]:
    if not text:
        return frozenset()
    tokens = {m.group(0).lower() for m in _TOKEN_RE.finditer(text)}
    # Drop very short and purely numeric tokens; they generate too much noise.
    return frozenset(t for t in tokens if len(t) >= 3 and not t.isdigit())

"""Knowledge layer: index of `knowledge/*.md` + lightweight retrieval.

In this MVP the index is keyword-based and lives entirely in process memory.
No external vector DB. We chunk each markdown file by H2/H3 sections, compute
a small set of metadata (file id, section title, fan-type tags, intent tags
parsed from filename + headings), and answer queries by token overlap +
metadata boost.

When the project grows to thousands of pages this will be replaced with a
real retriever (sqlite-vec or LiteLLM embeddings), but the contract stays:

    KnowledgeIndex.retrieve(query, *, max_chunks, max_chars) -> list[Snippet]
"""

from sonya.knowledge.loader import (
    KnowledgeChunk,
    KnowledgeStats,
    load_chunks,
)
from sonya.knowledge.retrieval import KnowledgeIndex, RetrievedSnippet

__all__ = [
    "KnowledgeChunk",
    "KnowledgeIndex",
    "KnowledgeStats",
    "RetrievedSnippet",
    "load_chunks",
]

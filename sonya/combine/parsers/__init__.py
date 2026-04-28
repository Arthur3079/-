"""Combine module 7 — parsers.

Submits four flavours of parsing jobs and stores their results so other
modules (warming, neuro-commenting, mass reactions) can use them as input.

Public surface:

* :class:`ParserExecutor` — Protocol describing the runtime that will
  actually call Telethon. Implementations live elsewhere (Sprint 7).
* :class:`StubParserExecutor` — Deterministic fake used in tests and to
  smoke-test the REST surface without a logged-in account.
* :mod:`schemas`    — Pydantic request/response models.
* :mod:`repository` — Async DB CRUD helpers.
"""

from sonya.combine.parsers.executor import (
    ExecutorResult,
    ParserExecutor,
    StubParserExecutor,
)

__all__ = [
    "ExecutorResult",
    "ParserExecutor",
    "StubParserExecutor",
]

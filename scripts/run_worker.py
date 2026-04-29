"""CLI entrypoint for the combine worker.

Run with::

    python -m scripts.run_worker

or::

    python scripts/run_worker.py

The script builds a :class:`PluginRegistry` with every combine plugin
registered in a fixed order. The runner polls them round-robin each
tick, so registration order also dictates which plugin gets the first
crack at work on every poll.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import NoReturn

from sonya.combine.accounts.repository import DEFAULT_OWNER_ID
from sonya.combine.commenting import CommentingWorkerPlugin
from sonya.combine.parsers import ParserWorkerPlugin
from sonya.combine.reactions import ReactionsWorkerPlugin
from sonya.combine.warming import WarmingWorkerPlugin
from sonya.combine.worker import (
    AccountRateLimiter,
    PluginRegistry,
    TelethonClientFactory,
    WorkerContext,
    WorkerRunner,
)
from sonya.config import get_settings
from sonya.db.session import async_session_factory


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def _build_runner() -> WorkerRunner:
    """Construct the runner with all production dependencies wired in."""

    settings = get_settings()
    registry = PluginRegistry()
    registry.register(ParserWorkerPlugin())
    registry.register(CommentingWorkerPlugin())
    registry.register(ReactionsWorkerPlugin())
    registry.register(WarmingWorkerPlugin())

    ctx = WorkerContext(
        session_factory=async_session_factory(),
        telethon_factory=TelethonClientFactory(settings),
        rate_limiter=AccountRateLimiter(),
        owner_id=DEFAULT_OWNER_ID,
    )
    return WorkerRunner(registry=registry, ctx=ctx)


async def _amain() -> None:
    runner = _build_runner()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runner.request_stop)
        except NotImplementedError:
            # Windows etc. — fall through; KeyboardInterrupt still works.
            pass

    logging.info("worker starting; plugins=%s", runner.registry.names)
    try:
        await runner.run_forever()
    finally:
        logging.info("worker stopped")


def main() -> NoReturn:  # pragma: no cover — thin CLI shim
    _configure_logging()
    asyncio.run(_amain())
    raise SystemExit(0)


if __name__ == "__main__":  # pragma: no cover
    main()

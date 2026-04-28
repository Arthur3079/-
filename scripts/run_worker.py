"""CLI entrypoint for the combine worker.

Run with::

    python -m scripts.run_worker

or::

    python scripts/run_worker.py

The script wires up an empty :class:`PluginRegistry` for now — concrete
plugins land in Sprints 7.2..7.5 (parser/commenting/reactions/warming).
Once a plugin module exists, register it here and the runner will pick
it up on the next process restart.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import NoReturn

from sonya.combine.accounts.repository import DEFAULT_OWNER_ID
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
    # Plugins are added by future sprints. The runner starts in a no-op
    # configuration: it polls every plugin (none yet), reports zero work
    # and sleeps. That's intentional — operators can roll the worker out
    # ahead of the actual logic landing.

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

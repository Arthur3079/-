"""The polling loop that drives every registered worker plugin.

Lifecycle::

    runner = WorkerRunner(registry=registry, ctx=ctx)
    await runner.run_forever()      # in production
    runner.request_stop()           # from a signal handler

The runner has no Telethon, DB, or HTTP knowledge — it just loops over
plugins, asks each one to do one tick of work, and sleeps if nobody had
anything to do. Errors raised by a plugin are caught, logged via
:class:`StepReport`, and don't abort the loop. Plugins are expected to
persist their own row state — the runner doesn't roll back transactions
on their behalf.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sonya.combine.worker.plugin import WorkerContext
from sonya.combine.worker.registry import PluginRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StepReport:
    """Aggregate result of a single :meth:`WorkerRunner.run_once` tick.

    ``did_work`` totals across plugins; ``errors`` is a list of
    ``(plugin_name, exception)`` tuples for the operator's logs.
    """

    did_work: int
    errors: list[tuple[str, BaseException]]


class WorkerRunner:
    """Driver for a :class:`PluginRegistry`."""

    def __init__(
        self,
        *,
        registry: PluginRegistry,
        ctx: WorkerContext,
        poll_interval: float = 1.0,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("poll_interval must be > 0")
        self._registry = registry
        self._ctx = ctx
        self._poll_interval = poll_interval
        self._stop_event = asyncio.Event()

    @property
    def registry(self) -> PluginRegistry:
        return self._registry

    async def run_once(self) -> StepReport:
        """Call :meth:`WorkerPlugin.step` on every plugin once."""

        did_work = 0
        errors: list[tuple[str, BaseException]] = []

        for plugin in self._registry:
            try:
                if await plugin.step(self._ctx):
                    did_work += 1
            except (Exception, asyncio.CancelledError) as exc:
                if isinstance(exc, asyncio.CancelledError):
                    # Honour cancellation — don't swallow it.
                    raise
                logger.exception("plugin %s.step raised", plugin.name)
                errors.append((plugin.name, exc))

        return StepReport(did_work=did_work, errors=errors)

    async def run_forever(self) -> None:
        """Loop until :meth:`request_stop` is called.

        Sleeps for ``poll_interval`` seconds between *empty* ticks; when
        a tick does work we immediately try again so a long backlog
        drains as fast as the plugins allow.
        """

        while not self._stop_event.is_set():
            report = await self.run_once()
            if report.did_work == 0 and not self._stop_event.is_set():
                await self._wait_or_stop()

    async def _wait_or_stop(self) -> None:
        """Sleep ``poll_interval`` seconds or until stop is requested."""

        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=self._poll_interval,
            )
        except TimeoutError:
            return

    def request_stop(self) -> None:
        """Ask :meth:`run_forever` to exit at the next checkpoint."""

        self._stop_event.set()

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()


__all__ = ["StepReport", "WorkerRunner"]

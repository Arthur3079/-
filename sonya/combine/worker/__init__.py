"""Worker scaffolding for the combine modules (Sprint 7.1).

The worker is the *runtime* counterpart of the bookkeeping REST surface
the combine modules already expose. A :class:`WorkerRunner` polls the
database via a small set of plugins (one per module — parser /
commenting / reactions / warming) and lets each plugin do one unit of
work per tick. The plugins themselves live in their respective modules
and land in Sprint 7.2..7.5; this package only ships the framework:

* :class:`WorkerPlugin` — Protocol every plugin implements.
* :class:`PluginRegistry` — registers plugins by name.
* :class:`WorkerContext` — bag of dependencies passed to every plugin.
* :class:`WorkerRunner` — the polling loop.
* :class:`AccountRateLimiter` — per-account semaphores + FloodWait
  back-off. Plugins use it to gate Telethon calls.
* :class:`TelethonClientFactory` — turns an ``Account`` (+ optional
  ``Proxy``) into a real ``telethon.TelegramClient``, decrypting the
  session blob and proxy password on the way through.
* ``scripts/run_worker.py`` — CLI entrypoint.
"""

from __future__ import annotations

from sonya.combine.worker.plugin import ClaimedWork, WorkerContext, WorkerPlugin
from sonya.combine.worker.rate_limit import AccountRateLimiter, FloodWaitError
from sonya.combine.worker.registry import PluginRegistry
from sonya.combine.worker.runner import WorkerRunner
from sonya.combine.worker.telethon_factory import (
    NoSessionError,
    TelethonClientFactory,
)

__all__ = [
    "AccountRateLimiter",
    "ClaimedWork",
    "FloodWaitError",
    "NoSessionError",
    "PluginRegistry",
    "TelethonClientFactory",
    "WorkerContext",
    "WorkerPlugin",
    "WorkerRunner",
]

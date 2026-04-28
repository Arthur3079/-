"""Worker plugin Protocol + the shared :class:`WorkerContext`.

A plugin's responsibility is narrow: given a :class:`WorkerContext`,
do *one* unit of work (claim a row, run it, persist the outcome) and
return whether it actually did anything. The runner calls every plugin
in turn each tick; if no plugin reported work, the runner sleeps for
``poll_interval`` seconds before the next tick.

Plugins are stateless, so a single instance can be shared across the
whole worker process. State that must persist across calls (e.g. the
last claimed job) lives in the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover — type-only import
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from sonya.combine.worker.rate_limit import AccountRateLimiter
    from sonya.combine.worker.telethon_factory import TelethonClientFactory


@dataclass(frozen=True, slots=True)
class ClaimedWork:
    """Lightweight descriptor returned by :meth:`WorkerPlugin.claim`.

    The worker uses the (kind, id) pair purely for logging; the plugin
    itself is responsible for re-loading whatever rows it needs in
    :meth:`WorkerPlugin.execute`. ``account_id`` is optional — some
    work units (e.g. observing a channel) aren't tied to an account.
    """

    kind: str
    id: int
    account_id: int | None = None


@dataclass(frozen=True, slots=True)
class WorkerContext:
    """Bag of dependencies handed to every plugin on every step.

    The runner builds one of these at startup and reuses it for the
    process's lifetime. Each plugin opens its own DB session via
    ``session_factory`` so concurrent ticks don't share a transaction.
    """

    session_factory: async_sessionmaker[AsyncSession]
    telethon_factory: TelethonClientFactory
    rate_limiter: AccountRateLimiter
    owner_id: int = 1


class WorkerPlugin(Protocol):
    """One module's worker logic.

    Each combine module (parser/commenting/reactions/warming) ships its
    own concrete plugin in a later sprint. The runner doesn't care
    which is which — it just polls them in registration order.
    """

    name: str

    async def step(self, ctx: WorkerContext) -> bool:
        """Try to do one unit of work.

        Returns:
            ``True`` if a row was claimed and processed (regardless of
            whether the outcome was success or failure — a failure that
            was correctly persisted still counts as work). ``False`` if
            there was nothing to do; the runner will then sleep before
            the next tick.
        """
        ...


__all__ = ["ClaimedWork", "WorkerContext", "WorkerPlugin"]

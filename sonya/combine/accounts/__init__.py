"""Module 1: Account Manager.

Sprint 0 ships the Telethon client pool and proxy wiring. CRUD / login flow
lands in Sprint 1.
"""

from __future__ import annotations

from sonya.combine.accounts.pool import ClientPool, PooledClient
from sonya.combine.accounts.proxy import build_telethon_proxy

__all__ = ["ClientPool", "PooledClient", "build_telethon_proxy"]

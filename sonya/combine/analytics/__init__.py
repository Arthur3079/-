"""Read-only analytics façade over the combine modules.

Sprint 6 introduces a single :class:`AnalyticsAggregator` that walks the
existing tables (accounts/proxies/warming/parsers/commenting/reactions)
with aggregating SQL queries and returns typed snapshots — no new tables,
no time-series, just a few SELECT ... GROUP BY round-trips.

The REST surface is exposed by :mod:`sonya_web.routers.combine_analytics`.
"""

from __future__ import annotations

from sonya.combine.analytics.aggregator import AnalyticsAggregator

__all__ = ["AnalyticsAggregator"]

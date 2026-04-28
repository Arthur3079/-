"""Observability: structured event log writes for runtime decisions.

Layer 1 wires `EventType` and `write_event` so every important decision
(inbound received, message sent, suppression applied, handoff required,
etc.) leaves an auditable row in the `events_log` table. Layers 2-5 will
add more event types and call sites.
"""

from __future__ import annotations

from sonya.observability.events import EventType, write_event

__all__ = ["EventType", "write_event"]

"""Structured event-log writer.

Every significant runtime decision should produce one row in `events_log`.
This is the only place that table is written from. The payload is a JSON
string to keep the schema future-proof (no per-event-type columns).

Usage::

    from sonya.observability import EventType, write_event

    await write_event(
        session,
        fan_id=client.fan_id,
        event_type=EventType.INBOUND_RECEIVED,
        payload={"len": len(text), "media": media_type.value},
    )

The `session` must be in an open transaction context — `write_event` only
adds the row; the surrounding caller is responsible for commit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sonya.db.models import EventLog


class EventType(StrEnum):
    """Catalogue of event types written to `events_log`.

    Naming convention: `<subject>_<verb_past>` where possible. Keep values
    stable across deploys — admin tooling and analytics filter on them.
    """

    # Inbound
    INBOUND_RECEIVED = "inbound_received"
    INBOUND_DEBOUNCED = "inbound_debounced"
    INBOUND_SKIPPED_PAUSED = "inbound_skipped_paused"
    INBOUND_SKIPPED_HANDOFF = "inbound_skipped_handoff"

    # Safety
    SAFETY_FLAGGED = "safety_flagged"
    SAFETY_REPLY_BLOCKED = "safety_reply_blocked"
    SUPPRESSION_APPLIED = "suppression_applied"
    SUPPRESSION_CLEARED = "suppression_cleared"
    HANDOFF_REQUIRED = "handoff_required"
    HANDOFF_CLEARED = "handoff_cleared"

    # CRM updates
    CRM_UPDATED = "crm_updated"
    STAGE_CHANGED = "stage_changed"
    RISK_LEVEL_CHANGED = "risk_level_changed"
    FAN_TYPE_UPDATED = "fan_type_updated"
    FACT_UPSERTED = "fact_upserted"
    FLAGS_UPDATED = "flags_updated"

    # Decisions
    ACTION_SELECTED = "action_selected"
    LLM_CALLED = "llm_called"
    LLM_FAILED = "llm_failed"
    VALIDATION_FAILED = "validation_failed"
    CADENCE_BLOCKED = "cadence_blocked"

    # Outbound
    MESSAGE_SENT = "message_sent"
    MESSAGE_SCHEDULED = "message_scheduled"
    DRY_RUN_OUTPUT = "dry_run_output"

    # Sales
    OFFER_SENT = "offer_sent"
    OFFER_BLOCKED = "offer_blocked"
    PURCHASE_RECORDED = "purchase_recorded"

    # Followups
    FOLLOWUP_ENQUEUED = "followup_enqueued"
    FOLLOWUP_EXECUTED = "followup_executed"
    FOLLOWUP_CANCELLED = "followup_cancelled"
    FOLLOWUP_SKIPPED = "followup_skipped"


async def write_event(
    session: AsyncSession,
    *,
    fan_id: int | None,
    event_type: EventType | str,
    payload: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> EventLog:
    """Append one row to `events_log`.

    `payload` is serialized to JSON; pass plain primitives (str/int/bool)
    or simple dicts/lists. Datetime values are converted to ISO strings.
    """
    et = event_type.value if isinstance(event_type, EventType) else str(event_type)
    payload_json: str | None = None
    if payload is not None:
        payload_json = json.dumps(payload, default=_json_default, sort_keys=True)
    row = EventLog(
        fan_id=fan_id,
        event_type=et,
        payload=payload_json,
        timestamp=timestamp or datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):  # StrEnum / Enum
        return value.value
    return str(value)

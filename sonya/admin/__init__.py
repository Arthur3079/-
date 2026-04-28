"""Operator tooling: pause/resume/handoff/inspect via Telegram admin chat or CLI.

The admin layer is **never** invoked from the fan-facing dialogue handler.
It runs in a separate Telethon NewMessage handler restricted to allowlisted
Telegram user IDs (see `sonya.config.Settings.admin_user_ids`). Every action
is appended to the `admin_actions` table for audit.
"""

from sonya.admin.commands import AdminCommandResult, dispatch_command
from sonya.admin.repository import (
    list_recent_actions,
    log_action,
    pause_client,
    resume_client,
    set_handoff,
    update_notes,
)

__all__ = [
    "AdminCommandResult",
    "dispatch_command",
    "list_recent_actions",
    "log_action",
    "pause_client",
    "resume_client",
    "set_handoff",
    "update_notes",
]

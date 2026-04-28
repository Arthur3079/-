"""Pure command dispatcher for the admin chat.

Parses `/cmd arg1 arg2 ...` strings, runs the action against the DB, and
returns a `AdminCommandResult` that the Telethon adapter (or a CLI) renders
to the operator. No Telegram-specific dependencies live here so the dispatch
is unit-testable.

Supported commands (all idempotent unless noted):

    /help                         — list commands
    /status                       — bot status (paused fans, recent actions)
    /pause <fan_id> [reason...]   — stop auto-replies for one fan
    /resume <fan_id>              — re-enable auto-replies
    /handoff <fan_id> [reason...] — operator takes over (alias for pause)
    /card <fan_id>                — render client card (name / lang / spend / flags / notes)
    /facts <fan_id>               — list known facts
    /note <fan_id> <text...>      — append a timestamped note
    /dump_prompt <fan_id>         — show the system prompt that would be sent next
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonya.admin.repository import (
    list_recent_actions,
    log_action,
    pause_client,
    resume_client,
    set_handoff,
    update_notes,
)
from sonya.config import Settings
from sonya.crm.classifier import classify_fan
from sonya.crm.facts import facts_dict
from sonya.db.models import Client, Followup, MessageDirection, SaleOutcome, SalesAttempt
from sonya.db.models import Message as MessageModel
from sonya.knowledge import KnowledgeIndex
from sonya.kpi.metrics import KPIEngine, render_fan_stats, render_global_metrics
from sonya.llm.prompts import (
    build_system_prompt,
    render_client_card,
    render_facts_block,
    render_orchestrator_hints,
)


@dataclass
class AdminCommandResult:
    """Outcome of one /command invocation. `text` is what to send back."""

    ok: bool
    text: str
    audit_action: str | None = None
    audit_target_fan_id: int | None = None
    audit_payload: str | None = None
    extra_lines: list[str] = field(default_factory=list)


HELP_TEXT = (
    "Sonya admin commands:\n"
    "/help — this message\n"
    "/status — bot health, paused fans, recent actions\n"
    "/stats [days] — KPI dashboard (default 30 days)\n"
    "/fan <fan_id> — detailed fan stats\n"
    "/top [spend|active] — top 10 fans\n"
    "/pause <fan_id> [reason...] — pause auto-replies for fan\n"
    "/resume <fan_id> — re-enable auto-replies\n"
    "/handoff <fan_id> [reason...] — operator takes over\n"
    "/card <fan_id> — client card\n"
    "/facts <fan_id> — known facts\n"
    "/note <fan_id> <text...> — append note\n"
    "/dump_prompt <fan_id> — show system prompt for next reply"
)


async def dispatch_command(
    session: AsyncSession,
    *,
    admin_user_id: int,
    raw_text: str,
    settings: Settings,
    knowledge: KnowledgeIndex | None = None,
) -> AdminCommandResult:
    """Parse `raw_text` and run the matching command."""
    parts = (raw_text or "").strip().split(maxsplit=2)
    if not parts or not parts[0].startswith("/"):
        return AdminCommandResult(ok=False, text="not a command. /help for list.")

    cmd = parts[0].lower()
    args_str = " ".join(parts[1:]) if len(parts) > 1 else ""

    if cmd == "/help":
        return AdminCommandResult(ok=True, text=HELP_TEXT)

    if cmd == "/status":
        return await _cmd_status(session)

    if cmd == "/stats":
        return await _cmd_stats(session, args_str=args_str)

    if cmd == "/fan":
        fan_id, _ = _parse_fan_id(args_str)
        if fan_id is None:
            return AdminCommandResult(ok=False, text="usage: /fan <fan_id>")
        return await _cmd_fan_stats(session, fan_id=fan_id)

    if cmd == "/top":
        return await _cmd_top(session, args_str=args_str)

    if cmd in {"/pause", "/resume", "/handoff", "/card", "/facts", "/note", "/dump_prompt"}:
        fan_id, rest = _parse_fan_id(args_str)
        if fan_id is None:
            return AdminCommandResult(
                ok=False, text=f"usage: {cmd} <fan_id> [...]; got: {args_str!r}"
            )

        if cmd == "/pause":
            return await _cmd_pause(
                session, admin_user_id=admin_user_id, fan_id=fan_id, reason=rest
            )
        if cmd == "/resume":
            return await _cmd_resume(session, admin_user_id=admin_user_id, fan_id=fan_id)
        if cmd == "/handoff":
            return await _cmd_handoff(
                session, admin_user_id=admin_user_id, fan_id=fan_id, reason=rest
            )
        if cmd == "/card":
            return await _cmd_card(session, fan_id=fan_id)
        if cmd == "/facts":
            return await _cmd_facts(session, fan_id=fan_id)
        if cmd == "/note":
            if not rest:
                return AdminCommandResult(ok=False, text="usage: /note <fan_id> <text...>")
            return await _cmd_note(session, admin_user_id=admin_user_id, fan_id=fan_id, note=rest)
        if cmd == "/dump_prompt":
            return await _cmd_dump_prompt(
                session, fan_id=fan_id, settings=settings, knowledge=knowledge
            )

    return AdminCommandResult(ok=False, text=f"unknown command {cmd!r}. /help for list.")


def _parse_fan_id(args: str) -> tuple[int | None, str]:
    """Pull the leading int. Return (fan_id, rest) or (None, '') on failure."""
    a = args.strip()
    if not a:
        return None, ""
    head, _, tail = a.partition(" ")
    try:
        return int(head), tail.strip()
    except ValueError:
        return None, a


async def _cmd_status(session: AsyncSession) -> AdminCommandResult:
    paused_q = await session.execute(
        select(func.count(Client.fan_id)).where(Client.is_paused.is_(True))
    )
    paused = int(paused_q.scalar_one() or 0)
    total_q = await session.execute(select(func.count(Client.fan_id)))
    total = int(total_q.scalar_one() or 0)
    recent = await list_recent_actions(session, limit=5)
    msgs_q = await session.execute(
        select(func.count(MessageModel.id)).where(
            MessageModel.timestamp >= datetime.now(UTC) - timedelta(hours=24),
        )
    )
    msgs_24h = int(msgs_q.scalar_one() or 0)
    sales_q = await session.execute(
        select(func.count(SalesAttempt.id)).where(
            SalesAttempt.outcome == SaleOutcome.PURCHASED,
            SalesAttempt.attempted_at >= datetime.now(UTC) - timedelta(days=7),
        )
    )
    purchases_7d = int(sales_q.scalar_one() or 0)
    follow_q = await session.execute(
        select(func.count(Followup.id)).where(
            Followup.executed_at.is_(None),
            Followup.cancelled.is_(False),
        )
    )
    pending_followups = int(follow_q.scalar_one() or 0)

    lines = [
        f"clients: {total} total ({paused} paused)",
        f"messages last 24h: {msgs_24h}",
        f"purchases last 7d: {purchases_7d}",
        f"pending followups: {pending_followups}",
        "recent admin actions:",
    ]
    if recent:
        for a in recent:
            ts = a.timestamp.strftime("%m-%d %H:%M")
            tgt = f"#{a.target_fan_id}" if a.target_fan_id else "-"
            lines.append(f"  {ts} {a.action_type} {tgt} {a.payload or ''}".rstrip())
    else:
        lines.append("  (none)")
    return AdminCommandResult(ok=True, text="\n".join(lines))


async def _cmd_pause(
    session: AsyncSession, *, admin_user_id: int, fan_id: int, reason: str
) -> AdminCommandResult:
    client = await pause_client(session, fan_id=fan_id, reason=reason or None)
    if client is None:
        return AdminCommandResult(ok=False, text=f"fan {fan_id} not found")
    await log_action(
        session,
        admin_user_id=admin_user_id,
        action_type="pause",
        target_fan_id=fan_id,
        payload=reason or None,
    )
    return AdminCommandResult(
        ok=True,
        text=f"paused fan {fan_id} ({reason or 'no reason'})",
        audit_action="pause",
        audit_target_fan_id=fan_id,
        audit_payload=reason or None,
    )


async def _cmd_resume(
    session: AsyncSession, *, admin_user_id: int, fan_id: int
) -> AdminCommandResult:
    client = await resume_client(session, fan_id=fan_id)
    if client is None:
        return AdminCommandResult(ok=False, text=f"fan {fan_id} not found")
    await log_action(
        session, admin_user_id=admin_user_id, action_type="resume", target_fan_id=fan_id
    )
    return AdminCommandResult(ok=True, text=f"resumed fan {fan_id}")


async def _cmd_handoff(
    session: AsyncSession, *, admin_user_id: int, fan_id: int, reason: str
) -> AdminCommandResult:
    client = await set_handoff(session, fan_id=fan_id, reason=reason or None)
    if client is None:
        return AdminCommandResult(ok=False, text=f"fan {fan_id} not found")
    await log_action(
        session,
        admin_user_id=admin_user_id,
        action_type="handoff",
        target_fan_id=fan_id,
        payload=reason or None,
    )
    return AdminCommandResult(ok=True, text=f"handoff set for fan {fan_id}")


async def _cmd_card(session: AsyncSession, *, fan_id: int) -> AdminCommandResult:
    client = await _get_client(session, fan_id)
    if client is None:
        return AdminCommandResult(ok=False, text=f"fan {fan_id} not found")
    fan_res = await classify_fan(session, client=client)
    facts = await facts_dict(session, fan_id=fan_id)
    msg_count_q = await session.execute(
        select(func.count(MessageModel.id)).where(MessageModel.fan_id == fan_id)
    )
    msg_count = int(msg_count_q.scalar_one() or 0)
    last_q = await session.execute(
        select(MessageModel)
        .where(MessageModel.fan_id == fan_id)
        .order_by(MessageModel.timestamp.desc())
        .limit(1)
    )
    last = last_q.scalar_one_or_none()

    lines = [f"fan_id: {fan_id}"]
    name = client.known_name or client.display_name or client.first_name or client.username
    if name:
        lines.append(f"name: {name}")
    lines.append(f"fan_type: {client.fan_type or '-'} (lite={fan_res.fan_type.value})")
    lines.append(f"language: {client.language or '-'}")
    lines.append(f"status: {client.status.value}")
    if client.is_paused:
        lines.append(f"PAUSED: {client.paused_reason or '(no reason)'}")
    lines.append(f"sales_status: {client.sales_status.value}")
    lines.append(
        f"spend lifetime: {client.total_spend_lifetime:.0f} stars / "
        f"30d: {client.total_spend_30d:.0f}"
    )
    lines.append(f"flags: {client.flags or '-'}")
    lines.append(f"messages: {msg_count}")
    if last is not None:
        lines.append(
            f"last message: {last.direction.value} @ {last.timestamp:%Y-%m-%d %H:%M} "
            f"({(last.content or '')[:80]!r})"
        )
    if facts:
        lines.append("facts:")
        for k, v in facts.items():
            lines.append(f"  {k}: {v}")
    if client.notes:
        lines.append(f"notes:\n{client.notes}")
    return AdminCommandResult(ok=True, text="\n".join(lines))


async def _cmd_facts(session: AsyncSession, *, fan_id: int) -> AdminCommandResult:
    facts = await facts_dict(session, fan_id=fan_id)
    if not facts:
        return AdminCommandResult(ok=True, text=f"no facts for fan {fan_id}")
    lines = [f"facts for fan {fan_id}:"]
    for k, v in facts.items():
        lines.append(f"  {k}: {v}")
    return AdminCommandResult(ok=True, text="\n".join(lines))


async def _cmd_note(
    session: AsyncSession, *, admin_user_id: int, fan_id: int, note: str
) -> AdminCommandResult:
    client = await update_notes(session, fan_id=fan_id, note=note)
    if client is None:
        return AdminCommandResult(ok=False, text=f"fan {fan_id} not found")
    await log_action(
        session,
        admin_user_id=admin_user_id,
        action_type="note",
        target_fan_id=fan_id,
        payload=note,
    )
    return AdminCommandResult(ok=True, text=f"note added to fan {fan_id}")


async def _cmd_dump_prompt(
    session: AsyncSession,
    *,
    fan_id: int,
    settings: Settings,
    knowledge: KnowledgeIndex | None,
) -> AdminCommandResult:
    """Reconstruct what the system prompt would look like right now.

    Doesn't call the LLM. Useful when the operator wants to know "why is Sonya
    answering this way?" — it shows the same `client_card / facts / knowledge
    / orchestrator_hints` blocks `DialogueService` would build for the next
    reply.
    """
    client = await _get_client(session, fan_id)
    if client is None:
        return AdminCommandResult(ok=False, text=f"fan {fan_id} not found")

    fan_res = await classify_fan(session, client=client)
    facts = await facts_dict(session, fan_id=fan_id)
    last_q = await session.execute(
        select(MessageModel)
        .where(MessageModel.fan_id == fan_id, MessageModel.direction == MessageDirection.INCOMING)
        .order_by(MessageModel.timestamp.desc())
        .limit(1)
    )
    last_in = last_q.scalar_one_or_none()
    last_text = (last_in.content or "") if last_in else ""

    snippets: list[str] = []
    used_files: list[str] = []
    if knowledge is not None and last_text and knowledge.chunk_count > 0:
        retrieved = knowledge.retrieve(
            last_text,
            max_chunks=settings.knowledge_max_snippets,
            max_chars=settings.knowledge_max_chars,
            fan_type=fan_res.fan_type.value,
        )
        for r in retrieved:
            snippets.append(r.text)
            used_files.append(r.file_id)

    hints = render_orchestrator_hints(intent=None, fan_type=fan_res.fan_type.value)
    prompt = build_system_prompt(
        client_card=render_client_card(client) or None,
        facts_block=render_facts_block(facts) or None,
        knowledge_snippets=snippets or None,
        orchestrator_hints=hints or None,
    )
    header = (
        f"---\nfan_id={fan_id}, fan_type_lite={fan_res.fan_type.value}, "
        f"used_knowledge={','.join(used_files) or '-'}\n---\n"
    )
    return AdminCommandResult(ok=True, text=header + prompt)


async def _get_client(session: AsyncSession, fan_id: int) -> Client | None:
    res = await session.execute(select(Client).where(Client.fan_id == fan_id))
    return res.scalar_one_or_none()


# ---- Phase 7: KPI commands ----


async def _cmd_stats(session: AsyncSession, *, args_str: str) -> AdminCommandResult:
    """KPI dashboard for the operator."""
    days = 30
    if args_str.strip().isdigit():
        days = int(args_str.strip())
        days = max(1, min(days, 365))

    metrics = await KPIEngine.global_metrics(session, window_days=days)
    text = render_global_metrics(metrics)
    return AdminCommandResult(ok=True, text=f"{text}\n\n(window: last {days} days)")


async def _cmd_fan_stats(session: AsyncSession, *, fan_id: int) -> AdminCommandResult:
    """Detailed stats for a single fan."""
    stats = await KPIEngine.fan_stats(session, fan_id=fan_id)
    if stats is None:
        return AdminCommandResult(ok=False, text=f"fan_id={fan_id} not found.")
    text = render_fan_stats(stats)
    return AdminCommandResult(ok=True, text=text)


async def _cmd_top(session: AsyncSession, *, args_str: str) -> AdminCommandResult:
    """Top 10 fans by spend or activity."""
    order = "spend"
    if args_str.strip().lower() in ("active", "activity", "recent"):
        order = "active"

    fans = await KPIEngine.top_fans(session, limit=10, order_by=order)
    if not fans:
        return AdminCommandResult(ok=True, text="No fans yet.")

    lines = [f"🏆 Top 10 fans (by {order}):", ""]
    for i, s in enumerate(fans, 1):
        name = s.display_name or f"#{s.fan_id}"
        lines.append(
            f"{i}. {name} — ${s.total_spend:.0f} | {s.total_messages_in} msgs | "
            f"{s.fan_type or '-'} | {s.current_stage or '-'}"
        )
    return AdminCommandResult(ok=True, text="\n".join(lines))

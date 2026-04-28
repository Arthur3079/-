"""Models for the GramGPT-style «combine» modules (accounts, proxies, …).

Sprint 0 of the GramGPT-clone roadmap lays the data foundation: a single-user
pool of Telegram accounts + proxies, plus an `owner_id` column on every new
table so a later sprint can switch on multi-tenancy without another migration.

These tables live side-by-side with the existing Sonya schema (clients,
messages, sales, …) and are imported into `target_metadata` via
``sonya.db.models`` re-exports — see the bottom of ``sonya/db/models.py``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sonya.db.base import Base

# ---------- ENUMS ----------


class AccountStatus(StrEnum):
    """Lifecycle of a managed Telegram account.

    * ``new``       — row created, no session yet.
    * ``warming``   — warm-up job running, not eligible for mass actions.
    * ``active``    — ready for work.
    * ``flood``     — hit a Telegram FloodWait / SlowMode, cooling off.
    * ``spam_block``— caught SpamBot restriction; still works in PMs with known contacts.
    * ``banned``    — account deleted / permanently banned.
    * ``retired``   — we voluntarily took it out of rotation.
    """

    NEW = "new"
    WARMING = "warming"
    ACTIVE = "active"
    FLOOD = "flood"
    SPAM_BLOCK = "spam_block"
    BANNED = "banned"
    RETIRED = "retired"


class AccountRole(StrEnum):
    """What this account is primarily used for.

    An account can be multi-role in practice, but the primary role drives the
    default schedules (e.g. a ``commenter`` never gets DM-chatter tasks).
    """

    COMMENTER = "commenter"
    CHATTER = "chatter"
    REACTOR = "reactor"
    PARSER = "parser"
    MULTI = "multi"


class ProxyType(StrEnum):
    SOCKS5 = "socks5"
    HTTP = "http"
    MTPROTO = "mtproto"


class ProxyHealth(StrEnum):
    UNKNOWN = "unknown"
    OK = "ok"
    SLOW = "slow"
    DEAD = "dead"


# ---------- OWNER ----------


class Owner(Base):
    """Logical account holder.

    For the initial single-user deployment there is exactly one row (id=1)
    and every other combine-table points at it. Having the column from day
    one avoids a painful schema rewrite if multi-tenancy is ever enabled.
    """

    __tablename__ = "owners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


# ---------- PROXY ----------


class Proxy(Base):
    """Outbound proxy used by one or more accounts.

    Passwords are stored in plaintext here; Sprint 1 will wrap them with
    symmetric encryption (``SECRET_KEY`` from .env).
    """

    __tablename__ = "combine_proxies"
    __table_args__ = (UniqueConstraint("owner_id", "host", "port", "username", name="uq_proxy"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("owners.id", ondelete="CASCADE"), nullable=False, index=True
    )

    type: Mapped[ProxyType] = mapped_column(Enum(ProxyType), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str | None] = mapped_column(String(128))
    password: Mapped[str | None] = mapped_column(String(256))
    mtproto_secret: Mapped[str | None] = mapped_column(String(128))

    health: Mapped[ProxyHealth] = mapped_column(
        Enum(ProxyHealth), default=ProxyHealth.UNKNOWN, nullable=False
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)

    accounts: Mapped[list[Account]] = relationship(back_populates="proxy")


# ---------- ACCOUNT ----------


class Account(Base):
    """Managed Telegram userbot account.

    Session blob (encrypted Telethon session) is stored as a single BLOB so
    the system has no dependency on per-account ``*.session`` files on disk
    — handy for containerised deploys.
    """

    __tablename__ = "combine_accounts"
    __table_args__ = (UniqueConstraint("owner_id", "phone", name="uq_account_phone"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("owners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proxy_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("combine_proxies.id", ondelete="SET NULL"), index=True
    )

    # --- Telegram identity ---
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))

    # --- Telethon credentials (app-level, usually shared across all accounts) ---
    api_id: Mapped[int | None] = mapped_column(Integer)
    api_hash: Mapped[str | None] = mapped_column(String(64))

    # --- Session blob (Telethon `StringSession`, encrypted at rest later) ---
    session_blob: Mapped[bytes | None] = mapped_column(LargeBinary)

    # --- Lifecycle ---
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus), default=AccountStatus.NEW, nullable=False
    )
    role: Mapped[AccountRole] = mapped_column(
        Enum(AccountRole), default=AccountRole.MULTI, nullable=False
    )
    trust_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Internal 0..100 score blending age, volume and ban history. *Not* an
    official Telegram metric — purely our own heuristic for scheduling."""

    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    spam_block_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    flood_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    note: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    proxy: Mapped[Proxy | None] = relationship(back_populates="accounts")


# ---------- WARMING ----------


class WarmingJobStatus(StrEnum):
    """Lifecycle of a warming job.

    * ``pending``   — created, no actions executed yet.
    * ``running``   — at least one action has been picked up by the executor.
    * ``paused``    — operator paused the job; executor skips it.
    * ``completed`` — every action is in a terminal state (done/failed/skipped).
    * ``cancelled`` — operator cancelled the job; remaining actions are skipped.
    """

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WarmingActionKind(StrEnum):
    """One step of a warming plan."""

    SUBSCRIBE_CHANNEL = "subscribe_channel"
    READ_HISTORY = "read_history"
    REACT_POST = "react_post"
    SEND_IDLE_MESSAGE = "send_idle_message"


class WarmingActionStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class WarmingJob(Base):
    """A scheduled warm-up sequence for one :class:`Account`.

    The plan is stored as a list of :class:`WarmingAction` rows so the
    executor can pick the next due action without recomputing the whole
    schedule, and so the operator can see step-by-step progress.
    """

    __tablename__ = "combine_warming_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("owners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("combine_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[WarmingJobStatus] = mapped_column(
        Enum(WarmingJobStatus), default=WarmingJobStatus.PENDING, nullable=False
    )
    target_trust_score: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    actions: Mapped[list[WarmingAction]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="WarmingAction.scheduled_at",
    )
    account: Mapped[Account] = relationship()


class WarmingAction(Base):
    """A single planned step within a :class:`WarmingJob`."""

    __tablename__ = "combine_warming_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("combine_warming_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    kind: Mapped[WarmingActionKind] = mapped_column(Enum(WarmingActionKind), nullable=False)
    target: Mapped[str | None] = mapped_column(String(255))
    """Free-form target identifier — channel username, peer id, etc."""

    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[WarmingActionStatus] = mapped_column(
        Enum(WarmingActionStatus), default=WarmingActionStatus.PENDING, nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text)
    trust_delta: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    """How much trust_score the parent account gains on success (capped at 100)."""

    job: Mapped[WarmingJob] = relationship(back_populates="actions")


# ---------- PARSERS ----------


class ParserKind(StrEnum):
    """Four parser flavours the combine supports.

    * ``users_in_chat``        — list members of a public chat/channel.
    * ``channels_of_user``     — list public channels a user has joined.
    * ``chat_history``         — fetch recent messages in a peer.
    * ``users_by_message``     — given a search query, find authors whose
      messages match it (used for keyword targeting).
    """

    USERS_IN_CHAT = "users_in_chat"
    CHANNELS_OF_USER = "channels_of_user"
    CHAT_HISTORY = "chat_history"
    USERS_BY_MESSAGE = "users_by_message"


class ParserJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ParserResultKind(StrEnum):
    USER = "user"
    CHANNEL = "channel"
    MESSAGE = "message"


class ParserJob(Base):
    """One parsing task — runs against a single :class:`Account`.

    The actual Telethon work is done by an external executor (Sprint 7);
    this row tracks intent + status + result count.
    """

    __tablename__ = "combine_parser_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("owners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("combine_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    kind: Mapped[ParserKind] = mapped_column(Enum(ParserKind), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    """Free-form target — channel username, user id, or search query."""

    params: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    """Per-kind extra knobs (e.g. ``{"limit": 200}``)."""

    status: Mapped[ParserJobStatus] = mapped_column(
        Enum(ParserJobStatus), default=ParserJobStatus.PENDING, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    results: Mapped[list[ParserResult]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class ParserResult(Base):
    """A single entity emitted by a parser job."""

    __tablename__ = "combine_parser_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("combine_parser_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    kind: Mapped[ParserResultKind] = mapped_column(Enum(ParserResultKind), nullable=False)
    tg_id: Mapped[int | None] = mapped_column(Integer)
    """Telegram-side numeric id (user id / channel id / message id)."""
    username: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(255))
    """Display name / channel title / message snippet."""
    extra: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)

    job: Mapped[ParserJob] = relationship(back_populates="results")


__all__ = [
    "Account",
    "AccountRole",
    "AccountStatus",
    "Owner",
    "ParserJob",
    "ParserJobStatus",
    "ParserKind",
    "ParserResult",
    "ParserResultKind",
    "Proxy",
    "ProxyHealth",
    "ProxyType",
    "WarmingAction",
    "WarmingActionKind",
    "WarmingActionStatus",
    "WarmingJob",
    "WarmingJobStatus",
]

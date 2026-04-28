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


__all__ = [
    "Account",
    "AccountRole",
    "AccountStatus",
    "Owner",
    "Proxy",
    "ProxyHealth",
    "ProxyType",
]

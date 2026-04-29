"""Модели БД: фаны, сообщения, факты, контент, продажи, follow-ups, события.

Схема построена на основе `knowledge/ai_training/18_memory_crm_playbook.md`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sonya.db.base import Base

# ---------- ENUMS ----------


class FanStatus(StrEnum):
    ACTIVE = "active"
    HOT = "hot"
    DORMANT = "dormant"
    GHOST = "ghost"
    LOST = "lost"
    BLOCKED = "blocked"


class SalesStatus(StrEnum):
    ACTIVE = "active"
    PAUSED_72H = "paused-72h"
    PAUSED_14D = "paused-14d"
    PAUSED_PERMANENT = "paused-permanent"


class MessageDirection(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"


class MessageMediaType(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
    DOCUMENT = "document"
    STICKER = "sticker"
    OTHER = "other"


class SaleOutcome(StrEnum):
    SENT = "sent"  # invoice/PPV отправлен
    OPENED = "opened"  # фан открыл
    PURCHASED = "purchased"
    DECLINED = "declined"
    IGNORED = "ignored"
    REFUNDED = "refunded"


# ---------- TABLES ----------


class Client(Base):
    """Фан (Telegram-юзер). PK = telegram user id."""

    __tablename__ = "clients"

    fan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))

    display_name: Mapped[str | None] = mapped_column(String(128))
    known_name: Mapped[str | None] = mapped_column(String(128))

    fan_type: Mapped[str | None] = mapped_column(String(8))  # A1..G3
    type_confidence: Mapped[str | None] = mapped_column(String(8))  # low/mid/high
    status: Mapped[FanStatus] = mapped_column(
        Enum(FanStatus), default=FanStatus.ACTIVE, nullable=False
    )

    language: Mapped[str | None] = mapped_column(String(8))
    timezone_guess: Mapped[str | None] = mapped_column(String(32))
    country_guess: Mapped[str | None] = mapped_column(String(64))

    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_active: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    total_spend_30d: Mapped[float] = mapped_column(Float, default=0.0)
    total_spend_lifetime: Mapped[float] = mapped_column(Float, default=0.0)
    ltv_estimate: Mapped[float] = mapped_column(Float, default=0.0)

    preferred_grain: Mapped[str | None] = mapped_column(String(64))  # csv "G3,G6"
    sales_status: Mapped[SalesStatus] = mapped_column(
        Enum(SalesStatus), default=SalesStatus.ACTIVE, nullable=False
    )

    flags: Mapped[str | None] = mapped_column(Text)  # csv: vulnerable_lite,off_platform...
    notes: Mapped[str | None] = mapped_column(Text)

    # Operator manual override: when True, the dialogue handler skips this fan
    # entirely and lets the human reply. Toggled via admin commands.
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    paused_reason: Mapped[str | None] = mapped_column(Text)

    # ---------- Lifecycle / journey (Layer 1) ----------
    # All stored as plain strings; valid values defined in `sonya.journey.stages`.

    current_stage: Mapped[str] = mapped_column(String(32), default="welcome", nullable=False)
    """Where in the relationship the fan is. See `Stage` enum."""

    risk_level: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    """Aggregate safety risk signal. See `RiskLevel` enum."""

    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Timestamp of the most recent fan→Sonya message. Distinct from
    `last_active` which historically tracked any activity."""

    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Timestamp of the most recent Sonya→fan message."""

    consecutive_outbound_without_reply: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    """How many Sonya messages have been sent in a row without an inbound
    reply. Reset to 0 on each inbound. Used by CadenceEngine (Layer 3)."""

    last_offer_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Timestamp of the most recent PPV/sale offer surfaced to the fan."""

    last_purchase_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Timestamp of the most recent successful purchase."""

    suppression_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When set and in the future, no proactive sends are allowed (followups,
    sales). The fan can still be replied to manually. Cleared when expired."""

    handoff_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """Distinct from `is_paused` (operator-driven manual pause): set by
    SafetyEngine when a hard-stop trigger fires (crisis, minor, off-platform
    pressure escalation). Implies the fan should reach a human, not Sonya."""

    messages: Mapped[list[Message]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    facts: Mapped[list[Fact]] = relationship(back_populates="client", cascade="all, delete-orphan")
    sales_attempts: Mapped[list[SalesAttempt]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    followups: Mapped[list[Followup]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )


class Message(Base):
    """Каждое входящее/исходящее сообщение."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.fan_id", ondelete="CASCADE"), nullable=False, index=True
    )
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)

    direction: Mapped[MessageDirection] = mapped_column(Enum(MessageDirection), nullable=False)
    media_type: Mapped[MessageMediaType] = mapped_column(
        Enum(MessageMediaType), default=MessageMediaType.TEXT, nullable=False
    )

    content: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    used_grain: Mapped[str | None] = mapped_column(String(8))
    used_playbook: Mapped[str | None] = mapped_column(String(64))
    llm_request_id: Mapped[str | None] = mapped_column(String(128))

    client: Mapped[Client] = relationship(back_populates="messages")


class Fact(Base):
    """known_facts CRM: имя/город/работа/питомец/ДР/хобби и т.д."""

    __tablename__ = "facts"
    __table_args__ = (UniqueConstraint("fan_id", "key", name="uq_facts_fan_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.fan_id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("messages.id", ondelete="SET NULL")
    )
    date_disclosed: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[str] = mapped_column(String(8), default="mid")  # low/mid/high

    client: Mapped[Client] = relationship(back_populates="facts")


class ContentSet(Base):
    """Контент-сет из content_catalog.md (47 наборов)."""

    __tablename__ = "content_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)  # T2-disco
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    theme: Mapped[str | None] = mapped_column(String(64))

    price_stars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_usd_equivalent: Mapped[float] = mapped_column(Float, default=0.0)

    files_path: Mapped[str | None] = mapped_column(Text)
    preview_path: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    target_types: Mapped[str | None] = mapped_column(Text)  # csv "B1,C4,D1"

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SalesAttempt(Base):
    """Попытка продажи: успешная или нет. Вторая обязательная таблица из ТЗ."""

    __tablename__ = "sales_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.fan_id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_set_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("content_sets.id", ondelete="SET NULL")
    )

    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    outcome: Mapped[SaleOutcome] = mapped_column(Enum(SaleOutcome), nullable=False)

    amount_stars: Mapped[int] = mapped_column(Integer, default=0)
    amount_usd_equivalent: Mapped[float] = mapped_column(Float, default=0.0)
    invoice_payload: Mapped[str | None] = mapped_column(String(128), index=True)

    grain_used: Mapped[str | None] = mapped_column(String(8))
    message_text: Mapped[str | None] = mapped_column(Text)
    reason_failed: Mapped[str | None] = mapped_column(Text)

    client: Mapped[Client] = relationship(back_populates="sales_attempts")


class Followup(Base):
    """Очередь cadence: ghost recovery, после покупки, ДР, ивенты."""

    __tablename__ = "followups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.fan_id", ondelete="CASCADE"), nullable=False, index=True
    )

    type: Mapped[str] = mapped_column(String(64), nullable=False)  # ghost_d7 / aftercare / birthday
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)

    client: Mapped[Client] = relationship(back_populates="followups")


class EventLog(Base):
    """Технические события для отладки/аудита."""

    __tablename__ = "events_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fan_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class PaymentEvent(Base):
    """Lifecycle events for one Telegram Stars / Bot API invoice.

    A `SalesAttempt` is the *intent* (we offered this content to that fan).
    `PaymentEvent` is the platform-level *fact* that comes back from the
    payment-bot: invoice_created, pre_checkout, successful, failed, refunded.
    Multiple events per sales_attempt is normal (created → pre_checkout →
    successful).
    """

    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.fan_id", ondelete="CASCADE"), nullable=False, index=True
    )
    sales_attempt_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sales_attempts.id", ondelete="SET NULL"), index=True
    )

    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # invoice_created / pre_checkout / successful / failed / refunded
    invoice_payload: Mapped[str | None] = mapped_column(String(128), index=True)
    telegram_charge_id: Mapped[str | None] = mapped_column(String(128), index=True)
    provider_charge_id: Mapped[str | None] = mapped_column(String(128))
    amount_stars: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str | None] = mapped_column(String(8))
    payload_raw: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ContentDelivery(Base):
    """A piece of content actually delivered to a fan after a successful sale."""

    __tablename__ = "content_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.fan_id", ondelete="CASCADE"), nullable=False, index=True
    )
    sales_attempt_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sales_attempts.id", ondelete="SET NULL"), index=True
    )
    content_set_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("content_sets.id", ondelete="SET NULL"), index=True
    )

    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    file_path: Mapped[str | None] = mapped_column(Text)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    delivery_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="delivered"
    )  # delivered / failed / partial


class AdminAction(Base):
    """Audit log: every operator action through the admin chat or CLI."""

    __tablename__ = "admin_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_fan_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    payload: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


# Re-export combine models so Alembic autogenerate and `target_metadata`
# pick them up without the user of this module caring where they live.
from sonya.db.models_auth import (  # noqa: E402,F401
    User,
    UserRole,
)
from sonya.db.models_combine import (  # noqa: E402,F401
    Account,
    AccountRole,
    AccountStatus,
    Owner,
    Proxy,
    ProxyHealth,
    ProxyType,
)

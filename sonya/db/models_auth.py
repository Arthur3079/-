"""Auth models for the multi-tenant combine deployment.

A ``User`` is a person who can sign in to the admin panel. Every user is
attached to exactly one ``Owner`` (the existing tenant table); deleting an
owner cascades to its users.

Several users can share the same owner (think: agency with one workspace
and multiple operators) but every API request is still scoped to the
owner — the JWT carries ``owner_id`` so the existing combine repositories
work unchanged.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sonya.db.base import Base


class UserRole(StrEnum):
    """Coarse role of a user within an owner.

    The combine REST endpoints don't currently differentiate roles —
    ``admin`` is reserved for future RBAC (e.g. only admins can register
    new users in the same workspace).
    """

    ADMIN = "admin"
    MEMBER = "member"


class User(Base):
    """A login-able operator inside an owner workspace."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("login", name="uq_users_login"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("owners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    login: Mapped[str] = mapped_column(String(64), nullable=False)
    # bcrypt produces a printable ASCII hash but we store it as bytes so the
    # column can also hold future hashers (e.g. argon2id) without migration.
    password_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.MEMBER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

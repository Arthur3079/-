"""Sprint 7.7: users (auth + multi-tenant).

Adds the ``users`` table that backs the JWT-based admin auth layer.
A user belongs to exactly one ``Owner``; deleting an owner cascades to its
users.

Revision ID: g4d5e6f7a8b9
Revises: f1c2d4e5b6a7
Create Date: 2026-04-28 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "g4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "f1c2d4e5b6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


USER_ROLE = ("admin", "member")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("owners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.LargeBinary(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(*USER_ROLE, name="userrole"),
            nullable=False,
            server_default="member",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("login", name="uq_users_login"),
    )
    op.create_index("ix_users_owner_id", "users", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_users_owner_id", table_name="users")
    op.drop_table("users")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="userrole").drop(bind, checkfirst=True)

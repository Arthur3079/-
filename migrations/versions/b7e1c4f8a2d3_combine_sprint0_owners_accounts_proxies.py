"""Combine sprint 0: owners, combine_accounts, combine_proxies.

Sprint 0 of the GramGPT-clone roadmap. Adds the data foundation for managing
many Telegram userbot accounts and their outbound proxies, plus an ``owners``
table so everything is tenant-ready from day one (the initial deployment
just seeds a single owner with id=1).

Revision ID: b7e1c4f8a2d3
Revises: a1b2c3d4e5f6
Create Date: 2026-04-28 19:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e1c4f8a2d3"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ACCOUNT_STATUS = (
    "new",
    "warming",
    "active",
    "flood",
    "spam_block",
    "banned",
    "retired",
)
ACCOUNT_ROLE = ("commenter", "chatter", "reactor", "parser", "multi")
PROXY_TYPE = ("socks5", "http", "mtproto")
PROXY_HEALTH = ("unknown", "ok", "slow", "dead")


def upgrade() -> None:
    op.create_table(
        "owners",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "combine_proxies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(*PROXY_TYPE, name="proxytype"),
            nullable=False,
        ),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=True),
        sa.Column("password", sa.String(length=256), nullable=True),
        sa.Column("mtproto_secret", sa.String(length=128), nullable=True),
        sa.Column(
            "health",
            sa.Enum(*PROXY_HEALTH, name="proxyhealth"),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("owner_id", "host", "port", "username", name="uq_proxy"),
    )
    op.create_index("ix_combine_proxies_owner_id", "combine_proxies", ["owner_id"])

    op.create_table(
        "combine_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("proxy_id", sa.Integer(), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("api_id", sa.Integer(), nullable=True),
        sa.Column("api_hash", sa.String(length=64), nullable=True),
        sa.Column("session_blob", sa.LargeBinary(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(*ACCOUNT_STATUS, name="accountstatus"),
            nullable=False,
            server_default="new",
        ),
        sa.Column(
            "role",
            sa.Enum(*ACCOUNT_ROLE, name="accountrole"),
            nullable=False,
            server_default="multi",
        ),
        sa.Column("trust_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("spam_block_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("flood_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["proxy_id"], ["combine_proxies.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("owner_id", "phone", name="uq_account_phone"),
        sa.UniqueConstraint("tg_user_id"),
    )
    op.create_index("ix_combine_accounts_owner_id", "combine_accounts", ["owner_id"])
    op.create_index("ix_combine_accounts_proxy_id", "combine_accounts", ["proxy_id"])

    # Seed the single-user owner so callers never have to remember to create it.
    op.execute(
        sa.text(
            "INSERT INTO owners (id, name, note, created_at, updated_at) "
            "VALUES (1, 'default', 'Auto-seeded by migration b7e1c4f8a2d3', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_combine_accounts_proxy_id", table_name="combine_accounts")
    op.drop_index("ix_combine_accounts_owner_id", table_name="combine_accounts")
    op.drop_table("combine_accounts")

    op.drop_index("ix_combine_proxies_owner_id", table_name="combine_proxies")
    op.drop_table("combine_proxies")

    op.drop_table("owners")

    # Enum types are only explicit objects on Postgres; SQLite ignores this.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for name in ("accountstatus", "accountrole", "proxytype", "proxyhealth"):
            sa.Enum(name=name).drop(bind, checkfirst=True)

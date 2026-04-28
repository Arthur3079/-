"""Combine sprint 5: reaction campaigns, targets, reactions.

Sprint 5 of the GramGPT-clone roadmap. Adds three tables backing module
6 (mass reactions):

* ``combine_reaction_campaigns`` — campaign config + lifecycle state.
* ``combine_reaction_targets``   — observed posts the campaign reacts to.
* ``combine_reactions``          — individual (target × account × emoji)
  attempts and their lifecycle.

Revision ID: f1c2d4e5b6a7
Revises: e9b3f7d2a1c8
Create Date: 2026-04-28 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1c2d4e5b6a7"
down_revision: str | Sequence[str] | None = "e9b3f7d2a1c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CAMPAIGN_STATUS = ("draft", "running", "paused", "archived")
TARGET_STATUS = ("pending", "planned", "done", "skipped")
REACTION_STATUS = ("pending", "posted", "failed", "skipped")


def upgrade() -> None:
    op.create_table(
        "combine_reaction_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("owners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*CAMPAIGN_STATUS, name="reactioncampaignstatus"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "target_channels",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "account_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "emojis",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "accounts_per_post", sa.Integer(), nullable=False, server_default="3"
        ),
        sa.Column(
            "max_reactions_per_day",
            sa.Integer(),
            nullable=False,
            server_default="200",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("paused_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text()),
    )
    op.create_index(
        "ix_combine_reaction_campaigns_owner_id",
        "combine_reaction_campaigns",
        ["owner_id"],
    )

    op.create_table(
        "combine_reaction_targets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "campaign_id",
            sa.Integer(),
            sa.ForeignKey(
                "combine_reaction_campaigns.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=255), nullable=False),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*TARGET_STATUS, name="reactiontargetstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "campaign_id",
            "channel",
            "tg_message_id",
            name="uq_reaction_target_per_campaign",
        ),
    )
    op.create_index(
        "ix_combine_reaction_targets_campaign_id",
        "combine_reaction_targets",
        ["campaign_id"],
    )

    op.create_table(
        "combine_reactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "target_id",
            sa.Integer(),
            sa.ForeignKey("combine_reaction_targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("combine_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("emoji", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*REACTION_STATUS, name="reactionstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
    )
    op.create_index(
        "ix_combine_reactions_target_id", "combine_reactions", ["target_id"]
    )
    op.create_index(
        "ix_combine_reactions_account_id", "combine_reactions", ["account_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_combine_reactions_account_id", table_name="combine_reactions"
    )
    op.drop_index(
        "ix_combine_reactions_target_id", table_name="combine_reactions"
    )
    op.drop_table("combine_reactions")
    op.drop_index(
        "ix_combine_reaction_targets_campaign_id",
        table_name="combine_reaction_targets",
    )
    op.drop_table("combine_reaction_targets")
    op.drop_index(
        "ix_combine_reaction_campaigns_owner_id",
        table_name="combine_reaction_campaigns",
    )
    op.drop_table("combine_reaction_campaigns")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for enum_name in (
            "reactionstatus",
            "reactiontargetstatus",
            "reactioncampaignstatus",
        ):
            sa.Enum(name=enum_name).drop(bind, checkfirst=True)

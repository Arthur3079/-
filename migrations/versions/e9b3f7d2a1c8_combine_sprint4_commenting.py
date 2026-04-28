"""Combine sprint 4: commenting campaigns, observed posts, comments.

Sprint 4 of the GramGPT-clone roadmap. Adds three tables backing module
3 (neuro-commenting):

* ``combine_commenting_campaigns`` — campaign config + lifecycle state.
* ``combine_commenting_posts``     — posts the worker has spotted in a
  campaign's target channels.
* ``combine_commenting_comments``  — generated comments + their post
  status.

Revision ID: e9b3f7d2a1c8
Revises: d8a1c5b9f2e4
Create Date: 2026-04-28 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9b3f7d2a1c8"
down_revision: str | Sequence[str] | None = "d8a1c5b9f2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CAMPAIGN_STATUS = ("draft", "running", "paused", "archived")
POST_STATUS = ("new", "queued", "commented", "skipped")
COMMENT_STATUS = ("pending", "generated", "posted", "failed", "skipped")


def upgrade() -> None:
    op.create_table(
        "combine_commenting_campaigns",
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
            sa.Enum(*CAMPAIGN_STATUS, name="commentingcampaignstatus"),
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
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column(
            "min_delay_seconds", sa.Integer(), nullable=False, server_default="60"
        ),
        sa.Column(
            "max_delay_seconds", sa.Integer(), nullable=False, server_default="300"
        ),
        sa.Column(
            "max_comments_per_day",
            sa.Integer(),
            nullable=False,
            server_default="20",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("paused_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text()),
    )
    op.create_index(
        "ix_combine_commenting_campaigns_owner_id",
        "combine_commenting_campaigns",
        ["owner_id"],
    )

    op.create_table(
        "combine_commenting_posts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "campaign_id",
            sa.Integer(),
            sa.ForeignKey(
                "combine_commenting_campaigns.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=255), nullable=False),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text()),
        sa.Column(
            "status",
            sa.Enum(*POST_STATUS, name="observedpoststatus"),
            nullable=False,
            server_default="new",
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "campaign_id",
            "channel",
            "tg_message_id",
            name="uq_observed_post_per_campaign",
        ),
    )
    op.create_index(
        "ix_combine_commenting_posts_campaign_id",
        "combine_commenting_posts",
        ["campaign_id"],
    )

    op.create_table(
        "combine_commenting_comments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "post_id",
            sa.Integer(),
            sa.ForeignKey("combine_commenting_posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("combine_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text()),
        sa.Column(
            "status",
            sa.Enum(*COMMENT_STATUS, name="commentstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("tg_comment_id", sa.BigInteger()),
    )
    op.create_index(
        "ix_combine_commenting_comments_post_id",
        "combine_commenting_comments",
        ["post_id"],
    )
    op.create_index(
        "ix_combine_commenting_comments_account_id",
        "combine_commenting_comments",
        ["account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_combine_commenting_comments_account_id",
        table_name="combine_commenting_comments",
    )
    op.drop_index(
        "ix_combine_commenting_comments_post_id",
        table_name="combine_commenting_comments",
    )
    op.drop_table("combine_commenting_comments")
    op.drop_index(
        "ix_combine_commenting_posts_campaign_id",
        table_name="combine_commenting_posts",
    )
    op.drop_table("combine_commenting_posts")
    op.drop_index(
        "ix_combine_commenting_campaigns_owner_id",
        table_name="combine_commenting_campaigns",
    )
    op.drop_table("combine_commenting_campaigns")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for enum_name in (
            "commentstatus",
            "observedpoststatus",
            "commentingcampaignstatus",
        ):
            sa.Enum(name=enum_name).drop(bind, checkfirst=True)

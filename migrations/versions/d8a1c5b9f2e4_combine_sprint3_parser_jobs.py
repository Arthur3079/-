"""Combine sprint 3: parser jobs and results.

Sprint 3 of the GramGPT-clone roadmap. Adds two tables backing module 7
(parsers):

* ``combine_parser_jobs``    — one row per submitted parsing task.
* ``combine_parser_results`` — entities (users / channels / messages)
  emitted by the executor for a job.

Revision ID: d8a1c5b9f2e4
Revises: c2f9a8b6d4e7
Create Date: 2026-04-28 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8a1c5b9f2e4"
down_revision: str | Sequence[str] | None = "c2f9a8b6d4e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PARSER_KIND = (
    "users_in_chat",
    "channels_of_user",
    "chat_history",
    "users_by_message",
)
PARSER_JOB_STATUS = ("pending", "running", "completed", "failed", "cancelled")
PARSER_RESULT_KIND = ("user", "channel", "message")


def upgrade() -> None:
    op.create_table(
        "combine_parser_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("owners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("combine_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum(*PARSER_KIND, name="parserkind"),
            nullable=False,
        ),
        sa.Column("target", sa.String(length=255), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "status",
            sa.Enum(*PARSER_JOB_STATUS, name="parserjobstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text()),
    )
    op.create_index(
        "ix_combine_parser_jobs_owner_id", "combine_parser_jobs", ["owner_id"]
    )
    op.create_index(
        "ix_combine_parser_jobs_account_id", "combine_parser_jobs", ["account_id"]
    )

    op.create_table(
        "combine_parser_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("combine_parser_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum(*PARSER_RESULT_KIND, name="parserresultkind"),
            nullable=False,
        ),
        sa.Column("tg_id", sa.Integer()),
        sa.Column("username", sa.String(length=64)),
        sa.Column("title", sa.String(length=255)),
        sa.Column("extra", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index(
        "ix_combine_parser_results_job_id", "combine_parser_results", ["job_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_combine_parser_results_job_id", table_name="combine_parser_results")
    op.drop_table("combine_parser_results")
    op.drop_index("ix_combine_parser_jobs_account_id", table_name="combine_parser_jobs")
    op.drop_index("ix_combine_parser_jobs_owner_id", table_name="combine_parser_jobs")
    op.drop_table("combine_parser_jobs")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for enum_name in ("parserresultkind", "parserjobstatus", "parserkind"):
            sa.Enum(name=enum_name).drop(bind, checkfirst=True)

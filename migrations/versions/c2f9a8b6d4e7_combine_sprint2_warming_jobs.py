"""Combine sprint 2: warming jobs and actions.

Sprint 2 of the GramGPT-clone roadmap. Adds two tables backing the
account-warming module:

* ``combine_warming_jobs``    — one row per scheduled warm-up sequence.
* ``combine_warming_actions`` — individual planned steps within a job.

Revision ID: c2f9a8b6d4e7
Revises: b7e1c4f8a2d3
Create Date: 2026-04-28 20:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2f9a8b6d4e7"
down_revision: str | Sequence[str] | None = "b7e1c4f8a2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


WARMING_JOB_STATUS = ("pending", "running", "paused", "completed", "cancelled")
WARMING_ACTION_KIND = (
    "subscribe_channel",
    "read_history",
    "react_post",
    "send_idle_message",
)
WARMING_ACTION_STATUS = ("pending", "done", "failed", "skipped")


def upgrade() -> None:
    op.create_table(
        "combine_warming_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*WARMING_JOB_STATUS, name="warmingjobstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "target_trust_score",
            sa.Integer(),
            nullable=False,
            server_default="50",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["account_id"], ["combine_accounts.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_combine_warming_jobs_owner_id", "combine_warming_jobs", ["owner_id"]
    )
    op.create_index(
        "ix_combine_warming_jobs_account_id", "combine_warming_jobs", ["account_id"]
    )

    op.create_table(
        "combine_warming_actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(*WARMING_ACTION_KIND, name="warmingactionkind"),
            nullable=False,
        ),
        sa.Column("target", sa.String(length=255), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(*WARMING_ACTION_STATUS, name="warmingactionstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("trust_delta", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["combine_warming_jobs.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_combine_warming_actions_job_id", "combine_warming_actions", ["job_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_combine_warming_actions_job_id", table_name="combine_warming_actions"
    )
    op.drop_table("combine_warming_actions")
    op.drop_index(
        "ix_combine_warming_jobs_account_id", table_name="combine_warming_jobs"
    )
    op.drop_index(
        "ix_combine_warming_jobs_owner_id", table_name="combine_warming_jobs"
    )
    op.drop_table("combine_warming_jobs")
    sa.Enum(name="warmingactionstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="warmingactionkind").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="warmingjobstatus").drop(op.get_bind(), checkfirst=True)

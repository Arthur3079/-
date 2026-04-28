"""Layer 1: lifecycle/journey fields on clients

Adds fields used by the Journey/Cadence/Safety engines (Layers 2-3):
- current_stage, risk_level
- last_inbound_at, last_outbound_at
- consecutive_outbound_without_reply
- last_offer_at, last_purchase_at
- suppression_until
- handoff_required

All new non-null columns ship `server_default` so existing rows backfill
cleanly. SQLite-friendly (`batch_alter_table`).

Revision ID: a1b2c3d4e5f6
Revises: 285d2e983578
Create Date: 2026-04-26 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "285d2e983578"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clients", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "current_stage",
                sa.String(length=32),
                nullable=False,
                server_default="welcome",
            )
        )
        batch_op.add_column(
            sa.Column(
                "risk_level",
                sa.String(length=16),
                nullable=False,
                server_default="none",
            )
        )
        batch_op.add_column(
            sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("last_outbound_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "consecutive_outbound_without_reply",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column("last_offer_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("last_purchase_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("suppression_until", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "handoff_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("clients", schema=None) as batch_op:
        batch_op.drop_column("handoff_required")
        batch_op.drop_column("suppression_until")
        batch_op.drop_column("last_purchase_at")
        batch_op.drop_column("last_offer_at")
        batch_op.drop_column("consecutive_outbound_without_reply")
        batch_op.drop_column("last_outbound_at")
        batch_op.drop_column("last_inbound_at")
        batch_op.drop_column("risk_level")
        batch_op.drop_column("current_stage")

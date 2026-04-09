"""Add trust_metric_snapshots (per-memory trust snapshots).

Revision ID: 002_trust_metric_snapshots
Revises: 001_initial
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "002_trust_metric_snapshots"
down_revision: str | None = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trust_metric_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trust_score", sa.Float(), nullable=False),
        sa.Column("time_decay_factor", sa.Float(), nullable=True),
        sa.Column("source_reliability_factor", sa.Float(), nullable=True),
        sa.Column("anomaly_penalty", sa.Float(), nullable=True),
        sa.Column("snapshot_reason", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_trust_metric_snapshots_memory_id",
        "trust_metric_snapshots",
        ["memory_id"],
    )
    op.create_index(
        "ix_trust_metric_snapshots_created_at",
        "trust_metric_snapshots",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_trust_metric_snapshots_created_at", table_name="trust_metric_snapshots")
    op.drop_index("ix_trust_metric_snapshots_memory_id", table_name="trust_metric_snapshots")
    op.drop_table("trust_metric_snapshots")

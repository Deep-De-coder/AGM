"""rule_violations table for policy engine.

Revision ID: 003_rule_violations
Revises: 002_trust_metric_snapshots
Create Date: 2026-04-09

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_rule_violations"
down_revision: Union[str, None] = "002_trust_metric_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rule_violations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rule_name", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_acknowledged", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("acknowledged_by", sa.String(255), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("auto_flagged", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_rule_violations_memory_id", "rule_violations", ["memory_id"])
    op.create_index("ix_rule_violations_agent_id", "rule_violations", ["agent_id"])
    op.create_index("ix_rule_violations_severity", "rule_violations", ["severity"])
    op.create_index("ix_rule_violations_detected_at", "rule_violations", ["detected_at"])
    op.create_index("ix_rule_violations_is_acknowledged", "rule_violations", ["is_acknowledged"])


def downgrade() -> None:
    op.drop_index("ix_rule_violations_is_acknowledged", table_name="rule_violations")
    op.drop_index("ix_rule_violations_detected_at", table_name="rule_violations")
    op.drop_index("ix_rule_violations_severity", table_name="rule_violations")
    op.drop_index("ix_rule_violations_agent_id", table_name="rule_violations")
    op.drop_index("ix_rule_violations_memory_id", table_name="rule_violations")
    op.drop_table("rule_violations")

"""Behavioral baseline, memory state, reality_score, sessions, nullable violation memory.

Revision ID: 004_behavioral_and_state
Revises: 003_rule_violations
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "004_behavioral_and_state"
down_revision: str | None = "003_rule_violations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "behavioral_baseline",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "behavioral_drift_score",
            sa.Float(),
            server_default="0.0",
            nullable=False,
        ),
    )
    op.add_column(
        "agents",
        sa.Column("system_prompt_hash", sa.String(128), nullable=True),
    )

    op.add_column(
        "memories",
        sa.Column(
            "memory_state",
            sa.String(32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
    )
    op.add_column(
        "memories",
        sa.Column("reality_score", sa.Float(), nullable=True),
    )

    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("context_hash", sa.String(256), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_sessions_context_hash", "sessions", ["context_hash"])

    op.drop_constraint("rule_violations_memory_id_fkey", "rule_violations", type_="foreignkey")
    op.alter_column(
        "rule_violations",
        "memory_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.create_foreign_key(
        "rule_violations_memory_id_fkey",
        "rule_violations",
        "memories",
        ["memory_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM rule_violations WHERE memory_id IS NULL"))
    op.drop_constraint("rule_violations_memory_id_fkey", "rule_violations", type_="foreignkey")
    op.alter_column(
        "rule_violations",
        "memory_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_foreign_key(
        "rule_violations_memory_id_fkey",
        "rule_violations",
        "memories",
        ["memory_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_index("ix_sessions_context_hash", table_name="sessions")
    op.drop_table("sessions")

    op.drop_column("memories", "reality_score")
    op.drop_column("memories", "memory_state")

    op.drop_column("agents", "system_prompt_hash")
    op.drop_column("agents", "behavioral_drift_score")
    op.drop_column("agents", "behavioral_baseline")

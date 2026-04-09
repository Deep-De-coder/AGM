"""Initial schema: pgvector, agents, memories, provenance log.

Revision ID: 001_initial
Revises:
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(128), nullable=False),
        sa.Column("source_identifier", sa.String(512), nullable=False),
        sa.Column(
            "safety_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("trust_score", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("is_flagged", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("flag_reason", sa.Text(), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
    )

    op.create_index("ix_memories_agent_id", "memories", ["agent_id"])
    op.create_index("ix_memories_is_deleted", "memories", ["is_deleted"])
    op.create_index("ix_memories_created_at", "memories", ["created_at"])

    op.create_table(
        "memory_provenance_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("performed_by_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "event_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["performed_by_agent_id"], ["agents.id"], ondelete="SET NULL"),
    )

    op.create_index("ix_provenance_memory_id", "memory_provenance_log", ["memory_id"])
    op.create_index("ix_provenance_timestamp", "memory_provenance_log", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_provenance_timestamp", table_name="memory_provenance_log")
    op.drop_index("ix_provenance_memory_id", table_name="memory_provenance_log")
    op.drop_table("memory_provenance_log")
    op.drop_index("ix_memories_created_at", table_name="memories")
    op.drop_index("ix_memories_is_deleted", table_name="memories")
    op.drop_index("ix_memories_agent_id", table_name="memories")
    op.drop_table("memories")
    op.drop_table("agents")

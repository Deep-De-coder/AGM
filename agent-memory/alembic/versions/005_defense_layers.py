"""Defense layers: DCA, behavioral hash, content addressing, vector clocks, quorum snapshots.

Revision ID: 005_defense_layers
Revises: 004_behavioral_and_state
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "005_defense_layers"
down_revision: str | None = "004_behavioral_and_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- agents: rolling behavioral identity ---
    op.add_column(
        "agents",
        sa.Column("behavioral_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column(
            "behavioral_hash_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "behavioral_vector",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # --- memories: content hash, causal, integrity ---
    op.add_column(
        "memories",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "memories",
        sa.Column(
            "content_hash_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "memories",
        sa.Column(
            "content_hash_valid",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "memories",
        sa.Column(
            "causal_parents",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "memories",
        sa.Column(
            "vector_clock",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "memories",
        sa.Column(
            "causal_depth",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )

    # --- trust_metric_snapshots: quorum ---
    op.add_column(
        "trust_metric_snapshots",
        sa.Column("quorum_fast_signal", sa.Float(), nullable=True),
    )
    op.add_column(
        "trust_metric_snapshots",
        sa.Column("quorum_medium_signal", sa.Float(), nullable=True),
    )
    op.add_column(
        "trust_metric_snapshots",
        sa.Column("quorum_slow_signal", sa.Float(), nullable=True),
    )
    op.add_column(
        "trust_metric_snapshots",
        sa.Column("quorum_status", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trust_metric_snapshots", "quorum_status")
    op.drop_column("trust_metric_snapshots", "quorum_slow_signal")
    op.drop_column("trust_metric_snapshots", "quorum_medium_signal")
    op.drop_column("trust_metric_snapshots", "quorum_fast_signal")

    op.drop_column("memories", "causal_depth")
    op.drop_column("memories", "vector_clock")
    op.drop_column("memories", "causal_parents")
    op.drop_column("memories", "content_hash_valid")
    op.drop_column("memories", "content_hash_verified_at")
    op.drop_column("memories", "content_hash")

    op.drop_column("agents", "behavioral_vector")
    op.drop_column("agents", "behavioral_hash_updated_at")
    op.drop_column("agents", "behavioral_hash")

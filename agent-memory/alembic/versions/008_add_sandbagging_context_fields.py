"""add sandbagging context fields: Session.context_type, Agent.evaluation_behavioral_vector

Revision ID: 008_add_sandbagging_context_fields
Revises: 007_add_taint_tracking_fields
Create Date: 2026-06-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "008_add_sandbagging_context_fields"
down_revision: str | None = "007_add_taint_tracking_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "context_type",
            sa.String(32),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "evaluation_behavioral_vector",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "evaluation_behavioral_vector")
    op.drop_column("sessions", "context_type")

"""add_taint_tracking_fields

Revision ID: 007_add_taint_tracking_fields
Revises: 006_add_session_id_fk_constraint
Create Date: 2026-06-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "007_add_taint_tracking_fields"
down_revision: str | None = "006_add_session_id_fk_constraint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column(
            "taint_score",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
    )
    op.add_column(
        "memories",
        sa.Column(
            "taint_sources",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("memories", "taint_sources")
    op.drop_column("memories", "taint_score")

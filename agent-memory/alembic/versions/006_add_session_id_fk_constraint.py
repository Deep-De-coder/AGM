"""add_session_id_fk_constraint

Revision ID: 006_add_session_id_fk_constraint
Revises: 005_defense_layers
Create Date: 2026-06-14

"""

from collections.abc import Sequence

from alembic import op

revision: str = "006_add_session_id_fk_constraint"
down_revision: str | None = "005_defense_layers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("memories") as batch_op:
        batch_op.create_foreign_key(
            "fk_memories_session_id_sessions",
            "sessions",
            ["session_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("memories") as batch_op:
        batch_op.drop_constraint(
            "fk_memories_session_id_sessions",
            type_="foreignkey",
        )

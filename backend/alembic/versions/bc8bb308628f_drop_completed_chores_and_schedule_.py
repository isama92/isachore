"""drop completed_chores and schedule_anchor

The occurrences table now holds both the scheduler and the completion history, and the
open occurrence's scheduled_for replaces the denormalised schedule_anchor, so both are
retired. Dev-only re-architecture with no data to preserve (the app was not yet in use),
so this is a plain structural drop - no backfill.

Revision ID: bc8bb308628f
Revises: 33c4638e6377
Create Date: 2026-07-21 06:23:01.833051

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bc8bb308628f"
down_revision: str | Sequence[str] | None = "33c4638e6377"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table("completed_chores")
    op.drop_column("chores", "schedule_anchor")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "chores",
        sa.Column("schedule_anchor", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_table(
        "completed_chores",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chore_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("scheduled_for", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chore_id"],
            ["chores.id"],
            name=op.f("fk_completed_chores_chore_id_chores"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["completed_by_user_id"],
            ["users.id"],
            name=op.f("fk_completed_chores_completed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_completed_chores")),
        sa.UniqueConstraint("chore_id", "scheduled_for", name=op.f("uq_completed_chores_chore_id")),
    )

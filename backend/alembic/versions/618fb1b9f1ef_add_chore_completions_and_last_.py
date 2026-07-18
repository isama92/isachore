"""add chore completions and last_completed_at

Revision ID: 618fb1b9f1ef
Revises: 2d82794703c5
Create Date: 2026-07-18 19:31:20.919332

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "618fb1b9f1ef"
down_revision: str | Sequence[str] | None = "2d82794703c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "completed_chores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chore_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
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
    op.add_column(
        "chores", sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("chores", "last_completed_at")
    op.drop_table("completed_chores")

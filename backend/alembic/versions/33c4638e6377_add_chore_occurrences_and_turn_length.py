"""add chore_occurrences and turn_length

Introduces the materialised occurrences table (the scheduler + history merged into
one timeline: one open row per chore = the current due occurrence and its assignee,
done rows = history) and the chores.turn_length knob for the "take turns" cadence.
Additive only: completed_chores and chores.schedule_anchor stay until the endpoint
rewrite retires them.

Revision ID: 33c4638e6377
Revises: b7c9d1e2f3a4
Create Date: 2026-07-21 05:58:38.645629

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "33c4638e6377"
down_revision: str | Sequence[str] | None = "b7c9d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chore_occurrences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chore_id", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("completed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name=op.f("fk_chore_occurrences_assignee_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["chore_id"],
            ["chores.id"],
            name=op.f("fk_chore_occurrences_chore_id_chores"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["completed_by_user_id"],
            ["users.id"],
            name=op.f("fk_chore_occurrences_completed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chore_occurrences")),
        sa.UniqueConstraint("chore_id", "scheduled_for", name="uq_occurrence_chore_scheduled"),
    )
    op.create_index(
        op.f("ix_chore_occurrences_chore_id"), "chore_occurrences", ["chore_id"], unique=False
    )
    # Partial unique index: at most one open occurrence per chore (the current due one).
    op.create_index(
        "uq_open_occurrence_per_chore",
        "chore_occurrences",
        ["chore_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.add_column(
        "chores", sa.Column("turn_length", sa.Integer(), server_default="1", nullable=False)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("chores", "turn_length")
    op.drop_index(
        "uq_open_occurrence_per_chore",
        table_name="chore_occurrences",
        postgresql_where=sa.text("status = 'open'"),
    )
    op.drop_index(op.f("ix_chore_occurrences_chore_id"), table_name="chore_occurrences")
    op.drop_table("chore_occurrences")

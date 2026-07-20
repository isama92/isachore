"""rename chores.last_completed_at to schedule_anchor

Recurrence is now schedule-anchored: the column stores the scheduled date of the
last cleared occurrence (the anchor for next_due = anchor + interval), not the
wall-clock completion time, so it is renamed for honesty. A plain rename keeps the
existing values; re-interpreted as anchors they reproduce roughly the prior due
date and self-heal on the next completion.

Revision ID: b7c9d1e2f3a4
Revises: 618fb1b9f1ef
Create Date: 2026-07-20 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c9d1e2f3a4"
down_revision: str | Sequence[str] | None = "618fb1b9f1ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("chores", "last_completed_at", new_column_name="schedule_anchor")


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("chores", "schedule_anchor", new_column_name="last_completed_at")

"""chore turns follow calendar

Revision ID: f3a1d6c84b20
Revises: 85c9542f74ba
Create Date: 2026-11-22 23:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a1d6c84b20"
down_revision: str | Sequence[str] | None = "85c9542f74ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # `server_default` plus NOT NULL makes every existing row valid in one pass. False is the
    # completion-counted turn every chore had before this column, so no backfill: an existing
    # chore keeps behaving exactly as it did until somebody ticks "Ignore skipped" on it.
    op.add_column(
        "chores",
        sa.Column("turns_follow_calendar", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("chores", "turns_follow_calendar")

"""chore occurrence skipped flag

Revision ID: 5c15efc03a8c
Revises: 7b2e5c9d4a13
Create Date: 2026-08-04 07:45:07.644966

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c15efc03a8c"
down_revision: str | Sequence[str] | None = "7b2e5c9d4a13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Marks a closure that produced no work (the occurrence was skipped, not done). Every
    # existing row is a real completion, so `server_default false` plus NOT NULL makes them
    # all valid in one pass with no follow-up UPDATE, the same shape as
    # chores.repeat_interval in 1758bd617791. The model mirrors the server_default and also
    # carries a Python-side default, so only this migration ever exercises it.
    op.add_column(
        "chore_occurrences",
        sa.Column("skipped", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("chore_occurrences", "skipped")

"""chore recurrence interval and weekdays

Revision ID: 1758bd617791
Revises: b4f826fa821a
Create Date: 2026-07-25 16:17:05.310722

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1758bd617791"
down_revision: str | Sequence[str] | None = "b4f826fa821a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # `server_default` plus NOT NULL makes every existing row valid in one pass, with no
    # follow-up UPDATE (the same shape as chores.turn_length in the initial schema). The
    # model mirrors the server_default so the two describe the same column; note that only
    # this migration exercises it, because the model also carries a Python-side default, so
    # the ORM never lets the database fill the value in.
    op.add_column(
        "chores",
        sa.Column("repeat_interval", sa.Integer(), server_default="1", nullable=False),
    )
    # Nullable with no server default on purpose: NULL is the meaningful value ("unpinned",
    # i.e. keep whatever weekday the occurrences already sit on), which is exactly how
    # every pre-existing weekly chore behaves. That is what makes a backfill unnecessary.
    op.add_column("chores", sa.Column("weekdays", sa.ARRAY(sa.SmallInteger()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Neither column creates a named type, so unlike the initial schema's enums there is
    # nothing to drop beyond the columns themselves.
    op.drop_column("chores", "weekdays")
    op.drop_column("chores", "repeat_interval")

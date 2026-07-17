"""add household_invitations.status

Revision ID: 12140d9e3c8e
Revises: a2d86c30696d
Create Date: 2026-07-17 23:36:03.796977

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "12140d9e3c8e"
down_revision: str | Sequence[str] | None = "a2d86c30696d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default backfills any existing rows so the NOT NULL constraint holds;
    # then drop it to match the model (Python-side default only), like the
    # users.status migration does.
    op.add_column(
        "household_invitations",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
    )
    op.alter_column("household_invitations", "status", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("household_invitations", "status")

"""backfill expired household invitations

Revision ID: 2d82794703c5
Revises: 367f5fe98e00
Create Date: 2026-07-18 16:13:59.296839

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2d82794703c5"
down_revision: str | Sequence[str] | None = "367f5fe98e00"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Reconcile the stored status with the clock at deploy time.

    Validity is now status-driven (the hourly sweep flips pending -> expired),
    so flip any already-stale pending invite now; otherwise it would read as
    live until the first sweep run."""
    op.execute(
        "UPDATE household_invitations SET status = 'expired' "
        "WHERE status = 'pending' AND expires_at <= now()"
    )


def downgrade() -> None:
    """No-op: a data reconciliation, and pending-vs-expired can't be inferred
    back once merged."""

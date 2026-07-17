"""add households.admin_id owner

Revision ID: df50b6e6f805
Revises: e0f788a32a8a
Create Date: 2026-07-17 20:55:20.030159

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "df50b6e6f805"
down_revision: str | Sequence[str] | None = "e0f788a32a8a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # admin_id is NOT NULL, so add it nullable, backfill existing rows, then
    # tighten. Backfill to each household's lowest-id member; for a member-less
    # legacy household fall back to the lowest-id site admin, then to any user,
    # so the NOT NULL constraint can always be applied (a household implies at
    # least one user exists).
    op.add_column("households", sa.Column("admin_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE households
        SET admin_id = COALESCE(
            (SELECT min(hm.user_id) FROM household_members hm
             WHERE hm.household_id = households.id),
            (SELECT min(id) FROM users WHERE is_admin),
            (SELECT min(id) FROM users)
        )
        """
    )
    op.alter_column("households", "admin_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_households_admin_id_users"), "households", "users", ["admin_id"], ["id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("fk_households_admin_id_users"), "households", type_="foreignkey")
    op.drop_column("households", "admin_id")

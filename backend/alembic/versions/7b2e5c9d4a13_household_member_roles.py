"""household member roles

Revision ID: 7b2e5c9d4a13
Revises: a91827f26ede
Create Date: 2026-08-03 10:12:47.882140

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7b2e5c9d4a13"
down_revision: str | Sequence[str] | None = "a91827f26ede"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # `server_default` plus NOT NULL makes every existing row valid in one pass, the same
    # shape as chores.repeat_interval, and the model mirrors the default so the two describe
    # the same column. Unlike that column this one carries NO Python-side default:
    # `add_member` states a role explicitly, so the database default only ever catches a
    # write path that forgot to - and catching it as the *least* privileged role is the point.
    op.add_column(
        "household_members",
        sa.Column("role", sa.String(length=30), server_default="helper", nullable=False),
    )
    # Then promote the one member per household who already had every power available on the
    # user surface: its owner. Everyone else lands on helper, which does take chore and tag
    # management, Statistics and History away from existing members until an owner promotes
    # them. That is deliberate: before this migration membership alone granted all of it, so
    # any other backfill would have to guess which of a household's members is the kid.
    op.execute(
        """
        UPDATE household_members hm
        SET role = 'organiser'
        FROM households h
        WHERE h.id = hm.household_id AND h.admin_id = hm.user_id
        """
    )
    # Index the user_id side. The primary key is (household_id, user_id), so a `WHERE user_id
    # = ?` lookup cannot use it, and Postgres indexes no FK automatically. Every membership
    # query filters user_id first (`member_household_ids`, `memberships_for`,
    # `role_in_household`, `is_active_member`, `member_of`), and roles put two of those on hot
    # paths: `memberships_for` runs on every /auth/me - so every mount, login and refresh - and
    # `role_in_household` on every gated write. Household tables are small, so this is cheap
    # insurance rather than a fix for a measured problem.
    op.create_index(
        op.f("ix_household_members_user_id"), "household_members", ["user_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_household_members_user_id"), table_name="household_members")
    # A plain String column, so there is no named type to drop alongside it.
    op.drop_column("household_members", "role")

"""household activity log

Revision ID: 89584c6f2687
Revises: 5c15efc03a8c
Create Date: 2026-08-04 10:53:59.454100

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "89584c6f2687"
down_revision: str | Sequence[str] | None = "5c15efc03a8c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # The household-facing activity log, read by a household's owner. Deliberately a separate
    # table from audit_events rather than a widening of it: that one is auth / 2FA / admin
    # user management, keys its action off a native `audit_action` enum (so a new value costs
    # an ALTER TYPE), and carries ip_address, which must never reach a household surface.
    # `action` here is a plain String with the closed set enforced at the schema layer, the
    # same pattern as household_members.role and users.status, so a new action needs no
    # migration. No backfill: there is no history to reconstruct.
    op.create_table(
        "household_log_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        # Nullable + SET NULL on all four references, the same departure from CASCADE
        # audit_events makes, so the trail outlives a hypothetical hard delete. Every entry
        # has a known actor in practice; the column is nullable for the foreign key alone.
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("impersonator_user_id", sa.Integer(), nullable=True),
        # SET NULL and nothing else: CASCADE would let an append-only log delete its own rows,
        # and RESTRICT would break a hard household delete, which cascades into `chores` in an
        # order Postgres does not guarantee against this table's own CASCADE. chore_title is
        # the snapshot that keeps a row readable either way.
        sa.Column("chore_id", sa.Integer(), nullable=True),
        sa.Column("chore_title", sa.String(length=255), nullable=True),
        # Which of a chore's fields moved on a chore_updated, by name and never by value. NULL
        # for every other action, and never an empty array: no fields moved means no entry.
        sa.Column("changed_fields", sa.ARRAY(sa.String(length=32)), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_household_log_entries_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["chore_id"],
            ["chores.id"],
            name=op.f("fk_household_log_entries_chore_id_chores"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_household_log_entries_household_id_households"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["impersonator_user_id"],
            ["users.id"],
            name=op.f("fk_household_log_entries_impersonator_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name=op.f("fk_household_log_entries_target_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_household_log_entries")),
    )
    # created_at alone for the retention prune, which scans it across every household; the
    # composite for the read, which is one or more owned households newest-first. The
    # composite also covers a household_id-only filter, so that column gets no index of its
    # own.
    op.create_index(
        op.f("ix_household_log_entries_created_at"),
        "household_log_entries",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_household_log_household_created_at",
        "household_log_entries",
        ["household_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # No named type to drop alongside the table: `action` is a plain String, not an enum.
    op.drop_index("ix_household_log_household_created_at", table_name="household_log_entries")
    op.drop_index(op.f("ix_household_log_entries_created_at"), table_name="household_log_entries")
    op.drop_table("household_log_entries")

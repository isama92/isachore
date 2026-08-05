"""chore occurrence updated_at

Revision ID: c8d5e21a473f
Revises: d7a3f81c62b4
Create Date: 2026-08-05 14:41:03.556218

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d5e21a473f"
down_revision: str | Sequence[str] | None = "d7a3f81c62b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # An occurrence stopped being write-once a while ago - completing one stamps four columns,
    # undoing clears them, and an edit can move `assignee_id` or re-date `scheduled_for` - so
    # `created_at` alone no longer answered "is this row still what it was".
    #
    # Its own revision rather than riding along with the timezone work in d7a3f81c62b4, even
    # though that revision already rewrites this table. Two reasons, and the second is the real
    # one: an operator rolling the timezone feature back should not have to drop an unrelated
    # column to do it, and a revision that does one thing is one you can reason about without
    # reading the other half.
    #
    # Three statements rather than `ADD COLUMN ... NOT NULL DEFAULT now()`, because `now()` is
    # volatile: with it Postgres cannot use the metadata-only fast path, so the ADD rewrites the
    # table and the backfill rewrites it again. Adding it nullable is metadata-only, the backfill
    # is the single rewrite, and `SET NOT NULL` then costs a scan rather than a third pass.
    op.add_column(
        "chore_occurrences",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # `created_at`, not the migration's clock: a row nothing has touched should report when it was
    # made. That covers every row, including the ones d7a3f81c62b4 re-anchored - re-anchoring
    # changed how a slot is *represented*, not anything a member did, and stamping "now" would
    # tell every reader somebody edited every occurrence the day this deployed.
    op.execute("UPDATE chore_occurrences SET updated_at = created_at")
    op.alter_column(
        "chore_occurrences",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("chore_occurrences", "updated_at")

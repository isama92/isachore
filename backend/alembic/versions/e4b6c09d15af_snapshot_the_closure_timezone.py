"""snapshot the household timezone on a closed occurrence

Revision ID: e4b6c09d15af
Revises: d7a3f81c62b4
Create Date: 2026-08-05 02:58:14.902731

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4b6c09d15af"
down_revision: str | Sequence[str] | None = "d7a3f81c62b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # `days_late` is a calendar judgement, not an instant: it is `completed_at`'s local date minus
    # `scheduled_for`'s. Read against the household's *current* zone it moves whenever the
    # household does, so a closure that was on time in Amsterdam started reporting a day late
    # after a move to Pacific/Niue - and History's badge, `punctuality` and `on_time_rate` all
    # moved with it. Snapshotting the zone at closing time makes the answer immutable, which is
    # the same thing `chore_occurrences.title` already does so history survives a rename.
    #
    # Nullable rather than NOT NULL with a default, deliberately: an *open* row has not been
    # judged yet, so NULL is the honest value for it and for every future one. Readers treat
    # NULL as "fall back to the household's current zone", which is the pre-existing behaviour.
    op.add_column(
        "chore_occurrences",
        sa.Column("completed_timezone", sa.String(64), nullable=True),
    )

    # Backfill closed rows from their household's zone, which is the best reconstruction
    # available and is exactly what the code did before this column: nothing recorded where a
    # household was at closing time, so there is nothing better to recover. It is also accurate
    # for the data that exists today, because d7a3f81c62b4 has just set every household to one
    # zone, so "the household's zone now" and "at closing time" are the same value.
    #
    # Left NULL for open rows, so the column keeps meaning "this closure was judged in this
    # zone" rather than "this is the household's zone, copied".
    op.execute(
        """
        UPDATE chore_occurrences o
        SET completed_timezone = h.timezone
        FROM chores c
        JOIN households h ON h.id = c.household_id
        WHERE o.chore_id = c.id
          AND o.status = 'done'
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to restore: the column only ever held a copy of what `households.timezone` says,
    # and dropping it returns every reader to that fallback. The cost is the drift itself coming
    # back, not any lost data.
    op.drop_column("chore_occurrences", "completed_timezone")

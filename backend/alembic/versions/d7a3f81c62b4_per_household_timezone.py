"""per-household timezone, and an updated_at on chore occurrences

Revision ID: d7a3f81c62b4
Revises: 89584c6f2687
Create Date: 2026-08-05 09:14:22.180446

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a3f81c62b4"
down_revision: str | Sequence[str] | None = "89584c6f2687"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Where the app has actually been running. A one-time backfill value, deliberately a literal
# here rather than a Settings field: it describes the past, not a deployment knob, and every
# household created after this migration carries an explicit zone from the API.
BACKFILL_ZONE = "Europe/Amsterdam"


def upgrade() -> None:
    """Upgrade schema."""
    # Every "today" question used to be answered against a UTC day, so at 01:30 in Amsterdam
    # the server still thought it was yesterday and My Chores showed the wrong day's chores.
    # A household is a physical place, so the zone belongs to it rather than to a user.
    #
    # server_default 'UTC' rather than the backfill value: it is the fail-closed floor for a
    # row that somehow bypassed the API (which requires an explicit zone), and reproducing the
    # old app-wide behaviour beats silently claiming a place the household is not in. The
    # UPDATE below is what moves the rows that exist today.
    op.add_column(
        "households",
        sa.Column("timezone", sa.String(64), server_default="UTC", nullable=False),
    )
    op.execute(sa.text("UPDATE households SET timezone = :zone").bindparams(zone=BACKFILL_ZONE))

    # Re-anchor scheduled slots from midnight UTC to local midnight in the household's zone,
    # which is the invariant the code now relies on: `scheduled_for` is local midnight of the
    # day the chore is due.
    #
    # `AT TIME ZONE` twice reinterprets the wall-clock reading rather than shifting by a fixed
    # amount: the first reads each value's UTC wall clock as a naive timestamp, the second says
    # "that reading was local". So DST is handled per row (-2h for a summer slot, -1h for a
    # winter one) with no hardcoded interval and no assumption about which rows are which.
    #
    # This is the ONE place a zone name reaches Postgres. Everything at runtime does its zone
    # maths in Python, because Postgres carries its own tz database and would raise inside SQL
    # on a name it does not share with Python's - a 500 from a query rather than a 422 from a
    # validator. Safe here precisely because every row holds BACKFILL_ZONE at this point.
    #
    # Unscheduled (`manual`) chores are excluded. Their `scheduled_for` is the moment the chore
    # was last completed, meaning "available since" rather than a deadline (see
    # `next_occurrence_after`), so it is already a correct instant and shifting it would
    # corrupt `days_since_last_completion`. `chore_occurrences.completed_at` is left alone for
    # the same reason and is not touched anywhere in this migration: it is stamped from
    # `datetime.now(UTC)` at the moment the button is pressed, so it has always been right.
    # Only the day boundary it was *read against* was wrong, and that is a code fix.
    #
    # On uq_occurrence_chore_scheduled: the second `AT TIME ZONE` is NOT injective across a
    # spring-forward gap (for Europe/Amsterdam on 29 March 2026, naive 01:30 and 02:30 both map
    # to 00:30Z), so "two slots are a day apart on the grid" is not by itself the reason this
    # cannot collide. The actual reason is that every row it touches sits at midnight UTC, which
    # is never inside a transition gap. The one exception is a chore that is scheduled *now* but
    # spent time as `manual`: those rows are anchored at completion timestamps, at arbitrary
    # times of day. Colliding still needs two of one chore's closures exactly one DST hour apart
    # on the transition date, which is why this is documented rather than guarded.
    op.execute(
        """
        UPDATE chore_occurrences o
        SET scheduled_for = (o.scheduled_for AT TIME ZONE 'UTC') AT TIME ZONE h.timezone
        FROM chores c
        JOIN households h ON h.id = c.household_id
        WHERE o.chore_id = c.id
          AND c.repeats <> 'manual'
        """
    )

    # Unrelated to the timezone work, and here only because it is a second column on a table
    # this revision already rewrites. An occurrence stopped being write-once a while ago -
    # completing one stamps four columns, undoing clears them, and an edit can move the
    # assignee or re-date the slot - so `created_at` alone no longer answers "is this what it
    # was".
    #
    # `server_default now()` plus NOT NULL makes every existing row valid without a follow-up
    # NULL sweep, the same shape as chore_occurrences.skipped in 5c15efc03a8c. Note `now()` is
    # volatile, so unlike a constant default this cannot use Postgres's metadata-only fast path:
    # the ADD COLUMN rewrites the table and the UPDATE below rewrites it again. Fine at household
    # scale, but it is two passes rather than one.
    #
    # The backfill sets every row to `created_at`, *including* the ones this revision just
    # re-anchored, which looks like a contradiction and is a deliberate choice: there is no edit
    # history to reconstruct, `created_at` is the only honest approximation available for a
    # pre-existing row, and re-anchoring changed how a slot is *represented* rather than anything
    # a member did. Stamping the migration's own clock instead would tell every reader that
    # somebody edited every occurrence the day this deployed, which is worse.
    op.add_column(
        "chore_occurrences",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute("UPDATE chore_occurrences SET updated_at = created_at")


def downgrade() -> None:
    """Downgrade schema.

    **Reversal is only faithful while every household still holds BACKFILL_ZONE.** The slot
    transform below is a true inverse, but it is the only half that is: this drops the column
    that records where each household is, and `upgrade()` then sets every row back to
    BACKFILL_ZONE unconditionally, because a re-added column cannot tell "never had a zone"
    from "had Pacific/Niue".

    Traced on a household that had moved to Pacific/Niue, for a slot due 25 July:

        stored 2026-07-25T11:00Z  ->  downgrade 2026-07-25T00:00Z  ->  re-upgrade 2026-07-24T22:00Z

    Note what does and does not survive. The slot moves by 13 hours but its local date is
    still the 25th, because it is now local midnight in Amsterdam instead of in Niue - so the
    chore still *reads* as due on the 25th. What is lost is the household's zone, and from then
    on it reckons "today" against a place it is not in, which is precisely the bug this
    revision exists to fix.

    So before rolling this back for real, snapshot the choices:

        SELECT id, name, timezone FROM households;

    and restore them afterwards. There is no way for the migration to do it: the values are
    gone by the time the re-upgrade runs.
    """
    op.drop_column("chore_occurrences", "updated_at")

    # Put the slots back on midnight UTC, mirroring the upgrade's transform. This has to run
    # BEFORE the column is dropped: it reads h.timezone, so dropping first would leave the
    # rows re-anchored with nothing left to reverse them by.
    op.execute(
        """
        UPDATE chore_occurrences o
        SET scheduled_for = (o.scheduled_for AT TIME ZONE h.timezone) AT TIME ZONE 'UTC'
        FROM chores c
        JOIN households h ON h.id = c.household_id
        WHERE o.chore_id = c.id
          AND c.repeats <> 'manual'
        """
    )
    op.drop_column("households", "timezone")

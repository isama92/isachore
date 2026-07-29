"""unscheduled chores: nullable start_date, revive terminated one-offs

Revision ID: 3c1f04a7e9d2
Revises: 1758bd617791
Create Date: 2026-07-29 10:12:44.918253

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c1f04a7e9d2"
down_revision: str | Sequence[str] | None = "1758bd617791"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # `manual` chores stop being one-offs and become unscheduled: repeatable on demand,
    # never due, and with no start date at all (it only ever seeded the first slot).
    op.alter_column("chores", "start_date", existing_type=sa.Date(), nullable=True)

    # Reopen every manual chore that the old one-off semantics left terminated, so it appears
    # on the unscheduled view again with its completion history intact. Ordering matters: this
    # reads chores.created_at, not start_date, partly because the UPDATE below is about to
    # erase the latter and partly because a chore's creation time is the honest "available
    # since" for a slot that no longer means a deadline.
    #
    # The new slot is one second past the chore's latest existing one, which is what keeps it
    # clear of uq_occurrence_chore_scheduled (strictly greater than every row for that chore)
    # without having to look for a free value. It does not affect the "last done" the view
    # reports, which comes from max(completed_at) over the done rows.
    #
    # The assignee is carried over from that row rather than advanced through the rotation
    # the way `_successor_assignee` would: reproducing the strategies in SQL is not worth it,
    # and whoever last held the chore is the least surprising person to still hold it.
    op.execute(
        """
        INSERT INTO chore_occurrences (chore_id, scheduled_for, assignee_id, status, created_at)
        SELECT c.id,
               COALESCE(latest.scheduled_for + interval '1 second', c.created_at),
               latest.assignee_id,
               'open',
               now()
        FROM chores c
        LEFT JOIN LATERAL (
            SELECT o.scheduled_for, o.assignee_id
            FROM chore_occurrences o
            WHERE o.chore_id = c.id
            ORDER BY o.scheduled_for DESC
            LIMIT 1
        ) latest ON true
        WHERE c.repeats = 'manual'
          AND c.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM chore_occurrences o2
              WHERE o2.chore_id = c.id AND o2.status = 'open'
          )
        """
    )

    op.execute("UPDATE chores SET start_date = NULL WHERE repeats = 'manual'")


def downgrade() -> None:
    """Downgrade schema."""
    # Approximate by necessity: the erased start dates are gone, so they are reconstructed
    # from each chore's earliest occurrence (its creation date where it somehow has none),
    # which is what the start date seeded in the first place. The UTC conversion is explicit
    # rather than a bare `::date` cast, which would read the session TimeZone and could shift
    # the reconstructed date by a day (the same reason the queries in home.py and stats.py
    # compute day bounds in Python).
    op.execute(
        """
        UPDATE chores c
        SET start_date = (COALESCE(
            (SELECT MIN(o.scheduled_for) FROM chore_occurrences o WHERE o.chore_id = c.id),
            c.created_at
        ) AT TIME ZONE 'UTC')::date
        WHERE c.start_date IS NULL
        """
    )
    op.alter_column("chores", "start_date", existing_type=sa.Date(), nullable=False)

    # Re-terminate the one-offs that have been done at least once, restoring the old
    # "completed and gone" state. A manual chore never completed keeps its open row, which is
    # what the old semantics gave it too.
    op.execute(
        """
        DELETE FROM chore_occurrences o
        USING chores c
        WHERE o.chore_id = c.id
          AND o.status = 'open'
          AND c.repeats = 'manual'
          AND EXISTS (
              SELECT 1 FROM chore_occurrences d
              WHERE d.chore_id = c.id AND d.status = 'done'
          )
        """
    )

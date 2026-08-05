import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chore import Chore
    from app.models.user import User


class OccurrenceStatus(enum.StrEnum):
    """Lifecycle of a single chore occurrence: `open` = assigned and due (the
    scheduler), `done` = completed (history). Stored as a plain String with the closed
    set enforced at the schema layer, same approach as users.status."""

    open = "open"
    done = "done"


class ChoreOccurrence(Base):
    """One occurrence of a chore on its recurrence grid - the scheduler and the
    completion history merged into a single timeline.

    A chore has at most one `open` occurrence at a time (the current due one, backed by
    a partial unique index); completing it flips the row to `done` and inserts the next
    open occurrence. The open row's `assignee_id` is the chore's current assignee, the
    only person shown on the Home due view. `title` is snapshotted on completion so
    history survives a rename (open rows read the live chore title). `assignee_id` and
    `completed_by_user_id` are ON DELETE SET NULL so history outlives a hard user delete;
    `chore_id` is ON DELETE RESTRICT to preserve history (chores are only soft-deleted).

    Skipping is the same closure with `skipped = True`, deliberately a flag on a `done`
    row rather than a third `OccurrenceStatus`. This table is read by two kinds of query:
    *structural* ones (which slot is taken, which row is open, which closure is latest)
    and *analytical* ones (how much work got done, by whom, on time). A flag keeps every
    structural query right by construction, since a skipped row is still a closed row,
    and confines the work to the analytical ones. A third status would instead have
    broken `free_slot_from`, `uq_open_occurrence_per_chore`, `undo_completion`'s
    latest-closure test and the history list, several of them silently. See `skipped`
    below for the resulting contract.
    """

    __tablename__ = "chore_occurrences"
    __table_args__ = (
        # One row per occurrence (open or done); rejects a double-complete of a slot.
        UniqueConstraint("chore_id", "scheduled_for", name="uq_occurrence_chore_scheduled"),
        # At most one open occurrence per chore (the current due one).
        Index(
            "uq_open_occurrence_per_chore",
            "chore_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        # Stats aggregations lead with status, then window on a timestamp. Composite
        # (status, completed_at) serves the done-in-range scans (completions over time,
        # punctuality, per-person, "done in range"); (status, scheduled_for) serves the
        # open+overdue scans (status donut, "overdue now"). A composite also covers a
        # status-only filter, so these two back most stats queries.
        Index("ix_occurrence_status_completed_at", "status", "completed_at"),
        Index("ix_occurrence_status_scheduled_for", "status", "scheduled_for"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chore_id: Mapped[int] = mapped_column(ForeignKey("chores.id", ondelete="RESTRICT"), index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Who is on the hook for this occurrence. NULL = unassigned/shared (shows to everyone).
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    status: Mapped[str] = mapped_column(String(16), default=OccurrenceStatus.open)
    # Snapshot taken on completion so history survives a rename; open rows read the
    # live chore title instead.
    title: Mapped[str | None] = mapped_column(String(255), default=None)
    # Who got credit for the completion (may differ from assignee_id via the credit
    # dialog). Set when the row is done.
    completed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # The household's timezone at the moment this row was closed, snapshotted for exactly the
    # reason `title` is: so a later change cannot rewrite history.
    #
    # `completed_at` is a plain instant and needs no help, but *lateness* is a calendar
    # judgement - `completed_at`'s local date minus `scheduled_for`'s - and read against the
    # household's *current* zone it moves whenever the household does. A closure that was on
    # time in Amsterdam started reporting a day late in Pacific/Niue. Reading both operands in
    # the zone the closure actually happened in makes the answer immutable.
    #
    # NULL on every open row (nothing has been judged yet) and on closures written before this
    # column existed, where the reader falls back to the household's current zone - the old
    # behaviour, which is also all the migration's backfill can honestly reconstruct.
    #
    # Do NOT reach for this on a "how long ago" measure. `days_since` on the unscheduled view and
    # Home's "done today" window are anchored to *now*, so they belong in the zone the household
    # is in now; mixing a snapshot operand with a live one compares two different calendars.
    completed_timezone: Mapped[str | None] = mapped_column(String(64), default=None)
    # A closure that produced no work: the occurrence was skipped rather than done. See
    # the class docstring for why this is a flag on a `done` row and not a third status.
    #
    # THE CONTRACT: `status == done` means "closed", NOT "work happened". So which way a
    # query goes depends on what it is asking, and the two kinds must not be confused:
    #
    #   - *Structural* reads ask which slots are taken, which row is open, which closure is
    #     the latest. They must NEVER filter: a skipped row occupies its slot and sits on the
    #     timeline exactly like a completion, and excluding it produces a slot collision on
    #     uq_occurrence_chore_scheduled - a 409 that retrying can never clear. These are
    #     `free_slot_from` (core/occurrences.py), `_reconcile_open_occurrence`'s `latest_done`
    #     (api/v1/chores.py), and both queries in `undo_completion` (api/v1/completions.py).
    #   - *Analytical* reads ask how much work happened, by whom, on time. They must ALWAYS
    #     add `skipped.is_(False)`, or a skip is silently counted as work done.
    #
    # There is exactly ONE analytical exception, commented at its call site: the progress
    # count in api/v1/home.py, where skipping a chore does tick "done today", because from
    # that list's point of view the chore was dealt with for today.
    #
    # A query that merely *fetches* closures and splits them afterwards (the history list,
    # stats' single pass) is neither, and filters per row instead.
    skipped: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # When the row last changed. An occurrence is no longer write-once - completing one
    # stamps four columns, undoing a completion clears them again, and an edit can move
    # `assignee_id` or re-date `scheduled_for` - so `created_at` alone stopped answering
    # "is this what it was". Backfilled from `created_at` rather than the migration's clock,
    # so a row nothing has touched reports the moment it was made.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chore: Mapped["Chore"] = relationship(back_populates="occurrences")
    # Two FKs point at users, so each relationship names its own foreign key.
    assignee: Mapped["User | None"] = relationship(foreign_keys=[assignee_id])
    completed_by: Mapped["User | None"] = relationship(foreign_keys=[completed_by_user_id])

"""Pure, DB-free recurrence logic for chore occurrences.

Occurrences are materialised rows with a stored `scheduled_for` (the occurrences
table), so this module no longer derives due dates; it computes where occurrences
fall on the recurrence grid. `first_occurrence` gives a chore's opening slot
(midnight UTC of its start date), and `next_occurrence_after` gives the slot that
follows completing one: it stays on the grid, so an early completion advances exactly
one interval while an overdue one skips the missed slots and jumps to the next future
one (see `advance_anchor`, its internal helper). `manual` chores are one-offs with no
next occurrence.

All datetimes are handled in UTC. There is no per-user timezone today, so "today"
is a UTC-day boundary for everyone (a per-user timezone is a future enhancement).
"""

from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from app.models import RepeatPeriod


class DueStatus(StrEnum):
    """Where a chore's next occurrence falls relative to today (UTC day)."""

    overdue = "overdue"
    today = "today"
    soon = "soon"


def _add_months(dt: datetime, months: int) -> datetime:
    """Add whole months, clamping the day to the target month's length and
    preserving the time-of-day and tzinfo (Jan 31 + 1mo -> Feb 28/29)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _add_interval(dt: datetime, repeats: RepeatPeriod) -> datetime:
    """The datetime one recurrence interval after `dt`. Never call with `manual`."""
    match repeats:
        case RepeatPeriod.daily:
            return dt + timedelta(days=1)
        case RepeatPeriod.weekly:
            return dt + timedelta(weeks=1)
        case RepeatPeriod.monthly:
            return _add_months(dt, 1)
        case RepeatPeriod.yearly:
            return _add_months(dt, 12)
        case _:  # manual has no interval
            raise ValueError(f"{repeats} has no recurrence interval")


def advance_anchor(
    scheduled_for: datetime, completed_at: datetime, repeats: RepeatPeriod
) -> datetime:
    """The last grid slot on or before the completion date, given the `scheduled_for`
    occurrence was completed at `completed_at`. `next_occurrence_after` adds one
    interval to this to get the successor occurrence's slot.

    Rolls forward on the recurrence grid, skipping every occurrence whose date is
    on or before the completion date: an early completion advances exactly one
    interval (the occurrence stays ahead), while an overdue completion jumps
    straight to the next strictly-future occurrence, so missed occurrences are not
    backfilled. Walking the grid from `scheduled_for` preserves the weekday /
    day-of-month / time-of-day."""
    if repeats == RepeatPeriod.manual:
        # A one-off has no interval; next_occurrence_after returns None for it anyway.
        return scheduled_for
    completed_date = completed_at.astimezone(UTC).date()
    anchor = scheduled_for
    nxt = _add_interval(anchor, repeats)
    while nxt.astimezone(UTC).date() <= completed_date:
        anchor, nxt = nxt, _add_interval(nxt, repeats)
    return anchor


def first_occurrence(start_date: date) -> datetime:
    """The first occurrence's due datetime: midnight UTC of the chore's start date
    (materialised as the initial open occurrence when a chore is created)."""
    return datetime(start_date.year, start_date.month, start_date.day, tzinfo=UTC)


def next_occurrence_after(
    scheduled_for: datetime, completed_at: datetime, repeats: RepeatPeriod
) -> datetime | None:
    """The due datetime of the occurrence following completion of `scheduled_for` at
    `completed_at`, or None for a `manual` one-off (which has no next occurrence).

    Composes advance_anchor (roll forward on the grid, skipping occurrences on or
    before the completion date) with one more interval, so an early completion advances
    exactly one step and an overdue one jumps to the next future slot - the same
    schedule-anchored recurrence the derived model used, now stamped onto the
    successor occurrence row."""
    if repeats == RepeatPeriod.manual:
        return None
    anchor = advance_anchor(scheduled_for, completed_at, repeats)
    return _add_interval(anchor, repeats)


def days_until_due(due: datetime, now: datetime) -> int:
    """Whole days from now's UTC date to the due date (negative = overdue).
    Date-based so a chore due at 00:00 today reads as due today, not overdue."""
    return (due.astimezone(UTC).date() - now.astimezone(UTC).date()).days


def days_late(scheduled_for: datetime, completed_at: datetime) -> int:
    """How many whole days late a completion was (>0 late, 0 on time, <0 early).
    The mirror of days_until_due for a past occurrence, using the same date-based
    UTC-day convention so a chore checked off at 23:00 on its due date reads as
    on time, not a day late."""
    return (completed_at.astimezone(UTC).date() - scheduled_for.astimezone(UTC).date()).days


def due_status(days: int) -> DueStatus:
    """Bucket a days-until-due value: overdue (<0), today (0), soon (any future
    day). There is no due-date cut-off; the Home view greys the dot for chores due
    more than a week out, but that is a display choice, not a filter."""
    if days < 0:
        return DueStatus.overdue
    if days == 0:
        return DueStatus.today
    return DueStatus.soon

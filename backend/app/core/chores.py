"""Pure, DB-free due-date logic for chores.

Chores store only a `start_date` + a `repeats` period and a denormalised
`last_completed_at`; there is no stored due date. The due date of the next
occurrence is derived here (completion-anchored recurrence): a never-completed
chore is first due on its start_date, and completing a chore schedules the next
occurrence one interval after the completion time. `manual` chores are one-offs
and have no next occurrence once completed.

All datetimes are handled in UTC. There is no per-user timezone today, so "today"
is a UTC-day boundary for everyone (a per-user timezone is a future enhancement).
"""

from calendar import monthrange
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.models import Chore, RepeatPeriod


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
        case RepeatPeriod.hourly:
            return dt + timedelta(hours=1)
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


def next_due(chore: Chore) -> datetime | None:
    """The chore's next due datetime (UTC), or None if it has no next occurrence
    (a completed `manual` one-off)."""
    if chore.last_completed_at is None:
        # First occurrence: midnight UTC of the start date.
        start = chore.start_date
        return datetime(start.year, start.month, start.day, tzinfo=UTC)
    if chore.repeats == RepeatPeriod.manual:
        return None
    return _add_interval(chore.last_completed_at, chore.repeats)


def days_until_due(due: datetime, now: datetime) -> int:
    """Whole days from now's UTC date to the due date (negative = overdue).
    Date-based so a chore due at 00:00 today reads as due today, not overdue."""
    return (due.astimezone(UTC).date() - now.astimezone(UTC).date()).days


def due_status(days: int) -> DueStatus:
    """Bucket a days-until-due value. `soon` covers everything in the future here;
    the caller restricts the list to the next 7 days."""
    if days < 0:
        return DueStatus.overdue
    if days == 0:
        return DueStatus.today
    return DueStatus.soon

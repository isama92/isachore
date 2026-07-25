"""Pure, DB-free recurrence logic for chore occurrences.

Occurrences are materialised rows with a stored `scheduled_for` (the occurrences
table), so this module no longer derives due dates; it computes where occurrences
fall on the recurrence grid. `first_occurrence` gives a chore's opening slot, and
`next_occurrence_after` gives the slot that follows completing one: it stays on the
grid, so an early completion advances exactly one slot while an overdue one skips the
missed slots and jumps to the next future one (see `advance_anchor`, its internal
helper). `manual` chores are one-offs with no next occurrence.

A `RecurrenceRule` bundles the period with how many periods to skip (`interval`) and,
for `weekly`, which weekdays the chore lands on. The rule deliberately does NOT carry
`start_date`: the start date only seeds the first occurrence, and every later slot is
walked from the previous one, so **the open occurrence's `scheduled_for` is the
schedule's live anchor**. That is what keeps a monthly chore on the day-of-month drift
it already has (Jan 31 -> Feb 28 -> Mar 28, never back to Mar 31) and what makes an
interval > 1 carry its phase in the occurrence chain instead of recomputing it from a
lattice the existing rows were never on.

All datetimes are handled in UTC. There is no per-user timezone today, so "today"
is a UTC-day boundary for everyone (a per-user timezone is a future enhancement).
"""

from calendar import monthrange
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from app.models import RepeatPeriod

DAYS_IN_WEEK = 7

# Upper bound on `interval`, mirrored by the schema layer's Field(le=...). Without one a
# yearly rule can push `_add_months` past datetime's year range (a 500); below 1, a slot
# walk would never advance.
MAX_INTERVAL = 365


class DueStatus(StrEnum):
    """Where a chore's next occurrence falls relative to today (UTC day)."""

    overdue = "overdue"
    today = "today"
    soon = "soon"


@dataclass(frozen=True, slots=True)
class RecurrenceRule:
    """How a chore repeats: the period, how many periods between occurrences, and (for
    `weekly` only) which weekdays it falls on.

    `weekdays` are Monday-first ordinals as produced by `date.weekday()`, so 0 = Monday
    .. 6 = Sunday. This is NOT ISO-8601, which numbers weekdays 1..7, and not JavaScript's
    `Date.getDay()`, which starts at Sunday. Empty means unpinned: the chore keeps
    whatever weekday its occurrences already sit on, which is how every chore predating
    weekday pinning behaves.

    Build one with `of()` rather than the constructor: it sorts and deduplicates the
    weekday set and drops it for the periods where it means nothing.
    """

    repeats: RepeatPeriod
    interval: int = 1
    weekdays: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        # Fail loudly on a nonsense rule rather than looping forever or overflowing
        # later. Deliberately a 500: user input is bounded at the schema layer, so
        # reaching here means a bad DB row or a hand-built rule.
        if not 1 <= self.interval <= MAX_INTERVAL:
            raise ValueError(f"interval must be 1..{MAX_INTERVAL}, got {self.interval}")
        if any(not 0 <= weekday < DAYS_IN_WEEK for weekday in self.weekdays):
            raise ValueError(f"weekdays must be 0..{DAYS_IN_WEEK - 1}, got {self.weekdays}")
        # Sort and deduplicate here rather than in `of`, so every construction path is
        # covered - including a DB row read straight into the constructor. `_weekly_step`
        # treats the tuple as sorted (it takes the first entry past its argument, and
        # weekdays[0] as the earliest of the week), so an unsorted tuple would not raise:
        # it would quietly produce a wrong schedule from the second slot onwards.
        object.__setattr__(self, "weekdays", tuple(sorted(set(self.weekdays))))

    @classmethod
    def of(
        cls,
        repeats: RepeatPeriod,
        interval: int = 1,
        weekdays: Iterable[int] | None = None,
    ) -> "RecurrenceRule":
        """Normalise stored or payload values into a rule, dropping the weekday set for
        every period but `weekly`, the only one it means anything for. Sorting and
        deduplication happen in `__post_init__` so they cover direct construction too."""
        pinned = weekdays if weekdays and repeats == RepeatPeriod.weekly else ()
        return cls(repeats=repeats, interval=interval, weekdays=tuple(pinned))

    @property
    def pinned(self) -> bool:
        """Whether this rule fixes which weekdays it falls on. `of` only keeps weekdays
        for `weekly`, so the period check is belt and braces for a hand-built rule; the
        emptiness check is what makes `weekdays[0]` below unreachable when unpinned."""
        return self.repeats == RepeatPeriod.weekly and bool(self.weekdays)


def _add_months(dt: datetime, months: int) -> datetime:
    """Add whole months, clamping the day to the target month's length and
    preserving the time-of-day and tzinfo (Jan 31 + 1mo -> Feb 28/29)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _weekly_step(weekday: int, rule: RecurrenceRule) -> int:
    """Whole days from `weekday` to the next selected one: the next selected day later in
    the same week when there is one, else the first selected day of the week `interval`
    weeks on.

    Note the asymmetry, which is the crux of multi-weekday recurrence: hopping weekdays
    *inside* one week is free, and only crossing the week boundary spends the interval.
    So Tue+Fri every two weeks chains Tue -> +3 Fri -> +11 Tue -> +3 Fri.

    Always returns >= 1 (worst case 7 - 6 + 0), which is what makes every walk over slots
    terminate.
    """
    later = [selected for selected in rule.weekdays if selected > weekday]
    if later:
        return later[0] - weekday
    return DAYS_IN_WEEK * rule.interval - weekday + rule.weekdays[0]


def next_slot_after(dt: datetime, rule: RecurrenceRule) -> datetime:
    """The next slot strictly after `dt`, preserving its time-of-day and tzinfo. Never
    call with `manual`, which has no interval (`next_occurrence_after` returns None for a
    one-off before it gets here)."""
    match rule.repeats:
        case RepeatPeriod.daily:
            return dt + timedelta(days=rule.interval)
        case RepeatPeriod.weekly:
            if rule.pinned:
                return dt + timedelta(days=_weekly_step(dt.astimezone(UTC).weekday(), rule))
            return dt + timedelta(weeks=rule.interval)
        case RepeatPeriod.monthly:
            return _add_months(dt, rule.interval)
        case RepeatPeriod.yearly:
            return _add_months(dt, 12 * rule.interval)
        case _:  # manual has no interval
            raise ValueError(f"{rule.repeats} has no recurrence interval")


def snap_to_slot(dt: datetime, rule: RecurrenceRule) -> datetime:
    """`dt` itself when it already falls on one of the rule's weekdays, else the nearest
    slot after it, at most six days on.

    Snapping re-phases the cycle from `dt` instead of spending the interval, so pinning
    weekdays onto a live chore moves its open occurrence by days, never by weeks. Only a
    pinned rule can move anything: for every other rule any datetime is a legitimate
    slot, because the phase is carried by the occurrence chain rather than a lattice.
    Idempotent, so callers can assign the result unconditionally instead of testing
    whether the slot is already valid.
    """
    if not rule.pinned:
        return dt
    weekday = dt.astimezone(UTC).weekday()
    forward = min((selected - weekday) % DAYS_IN_WEEK for selected in rule.weekdays)
    return dt + timedelta(days=forward)


def advance_anchor(
    scheduled_for: datetime, completed_at: datetime, rule: RecurrenceRule
) -> datetime:
    """The last grid slot on or before the completion date, given the `scheduled_for`
    occurrence was completed at `completed_at`. `next_occurrence_after` steps once more
    from this to get the successor occurrence's slot.

    Rolls forward on the recurrence grid, skipping every occurrence whose date is on or
    before the completion date: an early completion advances exactly one slot (the
    occurrence stays ahead), while an overdue completion jumps straight to the next
    strictly-future occurrence, so missed occurrences are not backfilled. Walking from
    `scheduled_for` preserves the weekday / day-of-month / time-of-day, and with an
    interval > 1 it preserves the cycle's phase, which is why this cannot be collapsed
    into a single "first slot after the completion date" call.

    Terminates because every `next_slot_after` branch advances by at least a day. The
    iteration count is roughly (completion date - scheduled_for) / step, so even a
    long-neglected daily chore costs a few thousand trivial iterations once.
    """
    if rule.repeats == RepeatPeriod.manual:
        # A one-off has no interval; next_occurrence_after returns None for it anyway.
        return scheduled_for
    completed_date = completed_at.astimezone(UTC).date()
    anchor = scheduled_for
    nxt = next_slot_after(anchor, rule)
    while nxt.astimezone(UTC).date() <= completed_date:
        anchor, nxt = nxt, next_slot_after(nxt, rule)
    return anchor


def first_occurrence(start_date: date, rule: RecurrenceRule) -> datetime:
    """The first occurrence's due datetime: midnight UTC of the chore's start date,
    snapped forward to the first selected weekday (materialised as the initial open
    occurrence when a chore is created).

    Snapping forward rather than onto a start-date-anchored lattice is what keeps a
    Saturday start with "every two weeks on Tuesday" due in three days instead of ten.
    """
    midnight = datetime(start_date.year, start_date.month, start_date.day, tzinfo=UTC)
    return snap_to_slot(midnight, rule)


def next_occurrence_after(
    scheduled_for: datetime, completed_at: datetime, rule: RecurrenceRule
) -> datetime | None:
    """The due datetime of the occurrence following completion of `scheduled_for` at
    `completed_at`, or None for a `manual` one-off (which has no next occurrence).

    Composes advance_anchor (roll forward on the grid, skipping occurrences on or before
    the completion date) with one more step, so an early completion advances exactly one
    slot and an overdue one jumps to the next future slot - schedule-anchored recurrence,
    stamped onto the successor occurrence row."""
    if rule.repeats == RepeatPeriod.manual:
        return None
    return next_slot_after(advance_anchor(scheduled_for, completed_at, rule), rule)


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

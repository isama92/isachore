"""Pure, DB-free recurrence logic for chore occurrences.

Occurrences are materialised rows with a stored `scheduled_for` (the occurrences
table), so this module no longer derives due dates; it computes where occurrences
fall on the recurrence grid. `first_occurrence` gives a chore's opening slot, and
`next_occurrence_after` gives the slot that follows completing one: it stays on the
grid, so an early completion advances exactly one slot while an overdue one skips the
missed slots and jumps to the next future one (see `advance_anchor`, its internal
helper). `manual` chores are unscheduled rather than one-off: they have no grid, so they
reopen at the moment they were completed and are never treated as due.

A `RecurrenceRule` bundles the period with how many periods to skip (`interval`) and,
for `weekly`, which weekdays the chore lands on. The rule deliberately does NOT carry
`start_date`: the start date only seeds the first occurrence, and every later slot is
walked from the previous one, so **the open occurrence's `scheduled_for` is the
schedule's live anchor**. That is what keeps a monthly chore on the day-of-month drift
it already has (Jan 31 -> Feb 28 -> Mar 28, never back to Mar 31) and what makes an
interval > 1 carry its phase in the occurrence chain instead of recomputing it from a
lattice the existing rows were never on.

Every function here takes the household's timezone, and that is not decoration: a chore is
due on a *day*, and which day it is depends on where the household is. The invariant the
whole module maintains is

    `scheduled_for` is local midnight of the day the chore is due, in `tz`.

so a chore due on 5 August in Amsterdam is stored as 2026-08-04T22:00Z in summer and
2026-01-04T23:00Z in winter, and reads back as local midnight on the 5th either way. Slots
are stored as instants (the column is `timestamptz`); the zone is what turns one back into a
calendar day. Datetimes arrive here UTC-aware, straight from Postgres, so every function
converts to `tz` first and works in local wall clock from there.

Two consequences of that conversion worth knowing:

- The `timedelta` arithmetic below is DST-correct *because* of it, with no special handling.
  Python adds to an aware datetime's wall-clock fields and keeps its tzinfo, and `ZoneInfo`
  then recomputes the offset from the shifted fields - so "the same time tomorrow" really is
  the same local time, an hour of absolute difference notwithstanding. `_add_months`'
  `replace()` behaves the same way. Doing this in UTC is what would drift.
- A step can land on a local time that does not exist, in the few zones whose DST transition
  is at midnight (`America/Santiago` among them). Python resolves that under `fold=0` to a
  real instant an hour off the nominal one, on the correct date. Nothing in the recurrence
  helpers reads a slot's time-of-day - every comparison is `.date()` - so the date being right
  is the whole requirement there.

  `local_day_bounds` is the exception and needs its own argument, because its result *is* used
  as an instant boundary in SQL. It holds: for a zone whose transition is at midnight, `fold=0`
  resolves the nonexistent local midnight using the pre-transition offset, and that instant is
  exactly the first moment of the new local day. Checked on `America/Santiago`, 6 September
  2026: day 5 ends at 04:00Z and day 6 begins at 04:00Z, so the windows tile with no gap, no
  overlap and no completion counted twice.

`completed_at` is the exception to all of this. It is a plain instant, correct in any zone,
and it is deliberately never *re-anchored*: nothing reinterprets its wall clock into another
zone, which would yield a different instant and so a row claiming the work happened at a time
it did not. It is, however, *chosen* at write time. A completion recorded on its due day
rather than at the moment the button was pressed is dated with `end_of_local_day` instead of
`clock.now()` (`POST /chores/{id}/complete`'s `backdate` flag, for the chore somebody did but
forgot to tick). Both are honest answers to "when was this done"; what stays forbidden is
moving one afterwards. It takes a `tz` here only to be *bucketed* into a local day.
"""

from calendar import monthrange
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.models import RepeatPeriod

DAYS_IN_WEEK = 7

# Upper bound on `interval`, mirrored by the schema layer's Field(le=...). Without one a
# yearly rule can push `_add_months` past datetime's year range (a 500); below 1, a slot
# walk would never advance.
MAX_INTERVAL = 365


class DueStatus(StrEnum):
    """Where a chore's next occurrence falls relative to today, as the chore's household
    reckons a day."""

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


def next_slot_after(dt: datetime, rule: RecurrenceRule, tz: ZoneInfo) -> datetime:
    """The next slot strictly after `dt`, preserving its local time-of-day. Never call with
    `manual`, which has no grid to step along (`next_occurrence_after` reopens an
    unscheduled chore at its completion moment before it gets here).

    Converting to `tz` up front is what makes every branch DST-correct: the arithmetic then
    runs on local wall-clock fields, so a daily chore due at local midnight stays at local
    midnight across a transition instead of sliding to 23:00 or 01:00."""
    local = dt.astimezone(tz)
    match rule.repeats:
        case RepeatPeriod.daily:
            return local + timedelta(days=rule.interval)
        case RepeatPeriod.weekly:
            if rule.pinned:
                return local + timedelta(days=_weekly_step(local.weekday(), rule))
            return local + timedelta(weeks=rule.interval)
        case RepeatPeriod.monthly:
            return _add_months(local, rule.interval)
        case RepeatPeriod.yearly:
            return _add_months(local, 12 * rule.interval)
        case _:  # manual has no interval
            raise ValueError(f"{rule.repeats} has no recurrence interval")


def snap_to_slot(dt: datetime, rule: RecurrenceRule, tz: ZoneInfo) -> datetime:
    """`dt` itself when it already falls on one of the rule's weekdays, else the nearest
    slot after it, at most six days on. Which weekday `dt` is on is a local question, hence
    the zone: an Amsterdam slot stored at 22:00Z on a Sunday is a Monday to the household.

    Snapping re-phases the cycle from `dt` instead of spending the interval, so pinning
    weekdays onto a live chore moves its open occurrence by days, never by weeks. Only a
    pinned rule can move anything: for every other rule any datetime is a legitimate
    slot, because the phase is carried by the occurrence chain rather than a lattice.
    Idempotent, so callers can assign the result unconditionally instead of testing
    whether the slot is already valid.
    """
    if not rule.pinned:
        return dt
    local = dt.astimezone(tz)
    forward = min((selected - local.weekday()) % DAYS_IN_WEEK for selected in rule.weekdays)
    return local + timedelta(days=forward)


def advance_anchor(
    scheduled_for: datetime, completed_at: datetime, rule: RecurrenceRule, tz: ZoneInfo
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
        # Unreachable from next_occurrence_after, which handles `manual` before it gets
        # here. Kept so a direct call cannot reach next_slot_after's ValueError: an
        # unscheduled chore has no grid to roll forward on, so its slot stands.
        return scheduled_for
    completed_date = completed_at.astimezone(tz).date()
    anchor = scheduled_for
    nxt = next_slot_after(anchor, rule, tz)
    while nxt.astimezone(tz).date() <= completed_date:
        anchor, nxt = nxt, next_slot_after(nxt, rule, tz)
    return anchor


def first_occurrence(start_date: date, rule: RecurrenceRule, tz: ZoneInfo) -> datetime:
    """The first occurrence's due datetime: local midnight of the chore's start date in the
    household's zone, snapped forward to the first selected weekday (materialised as the
    initial open occurrence when a chore is created).

    This is the one place a `date` becomes an instant, which is why `chores.start_date` can
    stay a plain calendar date: it records the day the household means to start, and the zone
    is what says when that day begins. Store it as midnight UTC instead and a household west
    of Greenwich gets a chore that was due yesterday the moment it is created.

    Snapping forward rather than onto a start-date-anchored lattice is what keeps a
    Saturday start with "every two weeks on Tuesday" due in three days instead of ten.
    """
    midnight = datetime(start_date.year, start_date.month, start_date.day, tzinfo=tz)
    return snap_to_slot(midnight, rule, tz)


def next_occurrence_after(
    scheduled_for: datetime, completed_at: datetime, rule: RecurrenceRule, tz: ZoneInfo
) -> datetime:
    """The due datetime of the occurrence following completion of `scheduled_for` at
    `completed_at`. Every period yields one, so a chore always has an open occurrence.

    For `manual` that is the completion moment itself: an unscheduled chore is repeatable
    on demand, so it reopens immediately, and its `scheduled_for` reads as "open since"
    rather than a deadline (nothing ever treats an unscheduled chore as due, see
    `app/api/v1/unscheduled.py`). The full timestamp, not its midnight, because
    `uq_occurrence_chore_scheduled` is per (chore, scheduled_for): a date would collide
    the second time the chore was done in one day.

    For the recurring periods, composes advance_anchor (roll forward on the grid, skipping
    occurrences on or before the completion date) with one more step, so an early completion
    advances exactly one slot and an overdue one jumps to the next future slot -
    schedule-anchored recurrence, stamped onto the successor occurrence row."""
    if rule.repeats == RepeatPeriod.manual:
        return completed_at
    return next_slot_after(advance_anchor(scheduled_for, completed_at, rule, tz), rule, tz)


def days_until_due(due: datetime, now: datetime, tz: ZoneInfo) -> int:
    """Whole days from today to the due date in the household's zone (negative = overdue).
    Date-based so a chore due at local midnight today reads as due today, not overdue.

    This is the function the whole feature exists for. Answered in UTC, it told someone in
    Amsterdam at 01:30 that today's chore was due tomorrow, because 01:30 local is still
    yesterday in UTC."""
    return (due.astimezone(tz).date() - now.astimezone(tz).date()).days


def days_since(moment: datetime, now: datetime, tz: ZoneInfo) -> int:
    """Whole days from `moment` to now in the household's zone (0 = earlier today,
    1 = yesterday). The mirror of days_until_due for a past moment, on the same date-based
    local-day convention: what the unscheduled view reports instead of a due date, since
    those chores are measured by how long since they were last done."""
    return (now.astimezone(tz).date() - moment.astimezone(tz).date()).days


def days_late(scheduled_for: datetime, completed_at: datetime, tz: ZoneInfo) -> int:
    """How many whole days late a completion was (>0 late, 0 on time, <0 early).
    The mirror of days_until_due for a past occurrence, using the same date-based
    local-day convention so a chore checked off at 23:00 local on its due date reads as
    on time, not a day late.

    `completed_at` is a plain instant and is never re-anchored anywhere; the zone here only
    decides which local day it fell on."""
    return (completed_at.astimezone(tz).date() - scheduled_for.astimezone(tz).date()).days


def local_day_bounds(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """The half-open [start, end) of the local day `now` falls in, as instants.

    What the endpoints filter `completed_at` between. Built in Python rather than as a
    `::date` cast, which would read Postgres's session TimeZone, and rather than an
    `AT TIME ZONE` on the column, which would hand Postgres a zone name from a household row:
    it carries its own copy of the tz database, so a name the two do not share would raise
    inside the query. A 500 from SQL is a worse failure than a 422 from a validator, and
    keeping the maths here means only Python ever has to know the name.

    `start + timedelta(days=1)` is wall-clock arithmetic on an aware datetime, so the window
    is 23 or 25 hours long across a DST transition - which is exactly what a local day is.
    """
    local = now.astimezone(tz)
    start = datetime(local.year, local.month, local.day, tzinfo=tz)
    return start, start + timedelta(days=1)


def end_of_local_day(moment: datetime, tz: ZoneInfo) -> datetime:
    """The last representable instant of the local day `moment` falls in. What a completion
    recorded on its due day is dated with, so it reads as on time and the successor advances
    exactly one slot instead of skipping the days that were missed.

    Derived from `local_day_bounds` rather than built here, which is what makes it correct
    for free in the awkward zones: a fall-back day really is 25 hours long, and a zone whose
    midnight does not exist still gets an instant on the right date.

    Two ways to write this that are wrong, both of which look right:

    - **Not `local_day_bounds(...)[1]`.** That bound is exclusive - it is the *next* local
      midnight, which is a different local date. Dating a completion with it makes
      `days_late` read 1 and lets `advance_anchor` roll a slot, i.e. it silently reintroduces
      exactly the skipped occurrence this exists to prevent.
    - **Not `datetime(y, m, d, 23, 59, 59, 999999, tzinfo=tz)`.** Besides duplicating the
      midnight construction, 23:59 is ambiguous in a zone that falls back at midnight, and
      `fold=0` there resolves to the earlier of the two occurrences - an hour before the day
      actually ends.

    One microsecond because `timestamptz` is microsecond-precision, so that is the exact
    predecessor of the exclusive bound.
    """
    _, day_end = local_day_bounds(moment, tz)
    return day_end - timedelta(microseconds=1)


def due_status(days: int) -> DueStatus:
    """Bucket a days-until-due value: overdue (<0), today (0), soon (any future
    day). There is no due-date cut-off; the Home view greys the dot for chores due
    more than a week out, but that is a display choice, not a filter."""
    if days < 0:
        return DueStatus.overdue
    if days == 0:
        return DueStatus.today
    return DueStatus.soon

from datetime import UTC, date, datetime

import pytest

from app.core.chores import (
    DueStatus,
    _add_interval,
    advance_anchor,
    days_until_due,
    due_status,
    next_due,
)
from app.models import Chore, RepeatPeriod


def _chore(*, start_date: date, repeats: RepeatPeriod, schedule_anchor: datetime | None) -> Chore:
    # An unpersisted Chore is enough to exercise the pure due-date logic.
    return Chore(
        household_id=1,
        title="t",
        start_date=start_date,
        repeats=repeats,
        assignment_type="manual",
        schedule_anchor=schedule_anchor,
    )


def test_add_interval_daily_weekly_preserve_time() -> None:
    base = datetime(2026, 7, 18, 14, 30, tzinfo=UTC)
    assert _add_interval(base, RepeatPeriod.daily) == datetime(2026, 7, 19, 14, 30, tzinfo=UTC)
    assert _add_interval(base, RepeatPeriod.weekly) == datetime(2026, 7, 25, 14, 30, tzinfo=UTC)


def test_add_interval_monthly_clamps_day_and_rolls_year() -> None:
    # Jan 31 + 1 month -> Feb 28 (2026 is not a leap year); time-of-day preserved.
    assert _add_interval(datetime(2026, 1, 31, 9, 0, tzinfo=UTC), RepeatPeriod.monthly) == datetime(
        2026, 2, 28, 9, 0, tzinfo=UTC
    )
    # December rolls into the next year.
    assert _add_interval(datetime(2026, 12, 15, tzinfo=UTC), RepeatPeriod.monthly) == datetime(
        2027, 1, 15, tzinfo=UTC
    )


def test_add_interval_yearly_clamps_leap_day() -> None:
    # Feb 29 (leap) + 1 year -> Feb 28.
    assert _add_interval(datetime(2028, 2, 29, tzinfo=UTC), RepeatPeriod.yearly) == datetime(
        2029, 2, 28, tzinfo=UTC
    )


def test_add_interval_manual_raises() -> None:
    with pytest.raises(ValueError, match="no recurrence interval"):
        _add_interval(datetime(2026, 7, 18, tzinfo=UTC), RepeatPeriod.manual)


def test_next_due_never_completed_is_start_date_midnight() -> None:
    chore = _chore(start_date=date(2026, 7, 10), repeats=RepeatPeriod.weekly, schedule_anchor=None)
    assert next_due(chore) == datetime(2026, 7, 10, tzinfo=UTC)


def test_next_due_is_one_interval_past_the_anchor() -> None:
    # next_due is a pure derivation from the anchor; time-of-day is preserved.
    chore = _chore(
        start_date=date(2026, 7, 10),
        repeats=RepeatPeriod.daily,
        schedule_anchor=datetime(2026, 7, 18, 14, 0, tzinfo=UTC),
    )
    assert next_due(chore) == datetime(2026, 7, 19, 14, 0, tzinfo=UTC)


def test_next_due_manual_completed_is_none() -> None:
    chore = _chore(
        start_date=date(2026, 7, 10),
        repeats=RepeatPeriod.manual,
        schedule_anchor=datetime(2026, 7, 15, tzinfo=UTC),
    )
    assert next_due(chore) is None


def test_next_due_manual_never_completed_is_start_date() -> None:
    chore = _chore(start_date=date(2026, 7, 10), repeats=RepeatPeriod.manual, schedule_anchor=None)
    assert next_due(chore) == datetime(2026, 7, 10, tzinfo=UTC)


def test_days_until_due_is_date_based_and_normalises_tz() -> None:
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    # Due at 00:00 today is "today" (0), not overdue, despite being in the past.
    assert days_until_due(datetime(2026, 7, 18, 0, 0, tzinfo=UTC), now) == 0
    assert days_until_due(datetime(2026, 7, 4, tzinfo=UTC), now) == -14
    assert days_until_due(datetime(2026, 7, 20, 9, 0, tzinfo=UTC), now) == 2


def test_due_status_buckets() -> None:
    assert due_status(-1) == DueStatus.overdue
    assert due_status(0) == DueStatus.today
    assert due_status(5) == DueStatus.soon


# --- advance_anchor (schedule-anchored recurrence) ------------------------


def test_advance_anchor_early_completion_advances_one_interval() -> None:
    # Completing tomorrow's occurrence today keeps it on the grid: next is the day
    # after tomorrow, not tomorrow again (the original bug).
    anchor = advance_anchor(
        datetime(2026, 7, 21, tzinfo=UTC),  # due tomorrow
        datetime(2026, 7, 20, 9, 0, tzinfo=UTC),  # completed today
        RepeatPeriod.daily,
    )
    assert anchor == datetime(2026, 7, 21, tzinfo=UTC)
    assert _add_interval(anchor, RepeatPeriod.daily) == datetime(2026, 7, 22, tzinfo=UTC)


def test_advance_anchor_on_time_completion_advances_to_next_day() -> None:
    anchor = advance_anchor(
        datetime(2026, 7, 20, tzinfo=UTC),  # due today
        datetime(2026, 7, 20, 14, 0, tzinfo=UTC),  # completed today
        RepeatPeriod.daily,
    )
    assert anchor == datetime(2026, 7, 20, tzinfo=UTC)
    assert _add_interval(anchor, RepeatPeriod.daily) == datetime(2026, 7, 21, tzinfo=UTC)


def test_advance_anchor_overdue_by_one_lands_tomorrow_not_today() -> None:
    # A chore due yesterday, completed today, is next due tomorrow (not today).
    anchor = advance_anchor(
        datetime(2026, 7, 19, tzinfo=UTC),  # due yesterday
        datetime(2026, 7, 20, 8, 0, tzinfo=UTC),  # completed today
        RepeatPeriod.daily,
    )
    assert anchor == datetime(2026, 7, 20, tzinfo=UTC)
    assert _add_interval(anchor, RepeatPeriod.daily) == datetime(2026, 7, 21, tzinfo=UTC)


def test_advance_anchor_missed_a_week_skips_backlog_to_tomorrow() -> None:
    # A daily chore ignored for a week clears in one completion: next due tomorrow,
    # the missed days are skipped rather than backfilled.
    anchor = advance_anchor(
        datetime(2026, 7, 13, tzinfo=UTC),  # due a week ago
        datetime(2026, 7, 20, 12, 0, tzinfo=UTC),  # completed today
        RepeatPeriod.daily,
    )
    assert anchor == datetime(2026, 7, 20, tzinfo=UTC)
    assert _add_interval(anchor, RepeatPeriod.daily) == datetime(2026, 7, 21, tzinfo=UTC)


def test_advance_anchor_weekly_overdue_preserves_weekday() -> None:
    # A weekly chore completed late on a different weekday stays on its original
    # weekday grid instead of jumping to the completion weekday.
    scheduled = datetime(2026, 6, 29, tzinfo=UTC)
    anchor = advance_anchor(
        scheduled,
        datetime(2026, 7, 15, 10, 0, tzinfo=UTC),  # a later, different weekday
        RepeatPeriod.weekly,
    )
    # Last weekly slot on or before the completion date, still on the same weekday.
    assert anchor == datetime(2026, 7, 13, tzinfo=UTC)
    assert anchor.weekday() == scheduled.weekday()
    assert _add_interval(anchor, RepeatPeriod.weekly) == datetime(2026, 7, 20, tzinfo=UTC)


def test_advance_anchor_monthly_overdue_stays_on_day_of_month() -> None:
    anchor = advance_anchor(
        datetime(2026, 1, 15, tzinfo=UTC),
        datetime(2026, 3, 10, tzinfo=UTC),
        RepeatPeriod.monthly,
    )
    assert anchor == datetime(2026, 2, 15, tzinfo=UTC)
    assert _add_interval(anchor, RepeatPeriod.monthly) == datetime(2026, 3, 15, tzinfo=UTC)


def test_advance_anchor_normalises_away_completion_time_of_day() -> None:
    # The completion time-of-day must not leak into the anchor: a midnight-grid
    # occurrence completed at 23:59 stays on the midnight grid (no drift).
    anchor = advance_anchor(
        datetime(2026, 7, 18, tzinfo=UTC),
        datetime(2026, 7, 20, 23, 59, tzinfo=UTC),
        RepeatPeriod.daily,
    )
    assert anchor == datetime(2026, 7, 20, tzinfo=UTC)
    assert (anchor.hour, anchor.minute) == (0, 0)


def test_advance_anchor_manual_returns_scheduled_for() -> None:
    # A one-off has no interval; the anchor is just marked non-null.
    scheduled = datetime(2026, 7, 20, tzinfo=UTC)
    assert advance_anchor(scheduled, datetime(2026, 7, 25, tzinfo=UTC), RepeatPeriod.manual) == (
        scheduled
    )

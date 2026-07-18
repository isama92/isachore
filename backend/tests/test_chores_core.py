from datetime import UTC, date, datetime

import pytest

from app.core.chores import DueStatus, _add_interval, days_until_due, due_status, next_due
from app.models import Chore, RepeatPeriod


def _chore(*, start_date: date, repeats: RepeatPeriod, last_completed_at: datetime | None) -> Chore:
    # An unpersisted Chore is enough to exercise the pure due-date logic.
    return Chore(
        household_id=1,
        title="t",
        start_date=start_date,
        repeats=repeats,
        assignment_type="manual",
        last_completed_at=last_completed_at,
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
    chore = _chore(
        start_date=date(2026, 7, 10), repeats=RepeatPeriod.weekly, last_completed_at=None
    )
    assert next_due(chore) == datetime(2026, 7, 10, tzinfo=UTC)


def test_next_due_completed_advances_one_interval_from_completion() -> None:
    chore = _chore(
        start_date=date(2026, 7, 10),
        repeats=RepeatPeriod.daily,
        last_completed_at=datetime(2026, 7, 18, 14, 0, tzinfo=UTC),
    )
    assert next_due(chore) == datetime(2026, 7, 19, 14, 0, tzinfo=UTC)


def test_next_due_manual_completed_is_none() -> None:
    chore = _chore(
        start_date=date(2026, 7, 10),
        repeats=RepeatPeriod.manual,
        last_completed_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    assert next_due(chore) is None


def test_next_due_manual_never_completed_is_start_date() -> None:
    chore = _chore(
        start_date=date(2026, 7, 10), repeats=RepeatPeriod.manual, last_completed_at=None
    )
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

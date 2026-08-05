from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.chores import (
    DueStatus,
    RecurrenceRule,
    advance_anchor,
    days_since,
    days_until_due,
    due_status,
    first_occurrence,
    next_occurrence_after,
    next_slot_after,
    snap_to_slot,
)
from app.models import RepeatPeriod

# Every case here predates household timezones and was written against a UTC day, so they all
# pass UTC explicitly and keep asserting exactly what they always did. The zone-specific
# behaviour lives in test_timezones.py, which is where a non-UTC zone belongs.
UTC_ZONE = ZoneInfo("UTC")

# Monday-first weekday ordinals, as `date.weekday()` numbers them (NOT ISO-8601's 1..7).
# Naming them here is also what pins 0 = Monday for the whole suite.
MON, TUE, WED, THU, FRI, SAT, SUN = range(7)

# July 2026, for reading the dates below: Mondays fall on the 6th, 13th, 20th and 27th,
# so Tuesdays are the 7th, 14th, 21st and 28th, and Fridays the 3rd, 10th, 17th, 24th and
# 31st. August 2026 opens on a Saturday, so its first Tuesday is the 4th.

DAILY = RecurrenceRule.of(RepeatPeriod.daily)
WEEKLY = RecurrenceRule.of(RepeatPeriod.weekly)
MONTHLY = RecurrenceRule.of(RepeatPeriod.monthly)
YEARLY = RecurrenceRule.of(RepeatPeriod.yearly)
MANUAL = RecurrenceRule.of(RepeatPeriod.manual)


def repeating(repeats: RepeatPeriod, every: int) -> RecurrenceRule:
    """An unpinned rule with an interval: `repeating(RepeatPeriod.daily, 2)` repeats every
    other day."""
    return RecurrenceRule.of(repeats, every)


def weekly_on(*weekdays: int, every: int = 1) -> RecurrenceRule:
    """A weekly rule pinned to `weekdays`, recurring every `every` weeks."""
    return RecurrenceRule.of(RepeatPeriod.weekly, every, weekdays)


# --- RecurrenceRule normalisation and guards --------------------------------


def test_rule_sorts_and_deduplicates_weekdays() -> None:
    assert weekly_on(FRI, TUE, TUE).weekdays == (TUE, FRI)


def test_rule_normalises_weekdays_on_direct_construction_too() -> None:
    # Normalising in __post_init__ rather than only in `of` is what covers a DB row read
    # straight into the constructor. `_weekly_step` treats the tuple as sorted, so an
    # unsorted one would not raise - it would quietly schedule the wrong days.
    assert RecurrenceRule(RepeatPeriod.weekly, 1, (FRI, TUE, TUE)).weekdays == (TUE, FRI)


def test_rule_drops_weekdays_for_every_period_but_weekly() -> None:
    # Weekdays only mean something for `weekly`; `of` refuses to carry them elsewhere so a
    # stale set cannot silently reactivate when a chore is switched back to weekly.
    assert RecurrenceRule.of(RepeatPeriod.daily, weekdays=[TUE, FRI]).weekdays == ()
    assert RecurrenceRule.of(RepeatPeriod.monthly, weekdays=[TUE]).weekdays == ()
    assert RecurrenceRule.of(RepeatPeriod.manual, weekdays=[TUE]).weekdays == ()
    # An empty selection is the same thing as no selection: unpinned.
    assert RecurrenceRule.of(RepeatPeriod.weekly, weekdays=[]).weekdays == ()


def test_rule_pinned_only_when_weekly_with_weekdays() -> None:
    assert weekly_on(TUE).pinned is True
    assert WEEKLY.pinned is False
    assert RecurrenceRule.of(RepeatPeriod.daily, weekdays=[TUE]).pinned is False


def test_rule_rejects_out_of_range_interval() -> None:
    # Below 1 a slot walk would never advance; above the cap a yearly rule can push
    # _add_months past datetime's year range.
    with pytest.raises(ValueError, match="interval must be"):
        RecurrenceRule.of(RepeatPeriod.daily, 0)
    with pytest.raises(ValueError, match="interval must be"):
        RecurrenceRule.of(RepeatPeriod.daily, 366)
    # Both ends of the accepted range, so an off-by-one in the bound is fully caught.
    assert RecurrenceRule.of(RepeatPeriod.daily, 1).interval == 1
    assert RecurrenceRule.of(RepeatPeriod.daily, 365).interval == 365


def test_rule_rejects_out_of_range_weekday() -> None:
    with pytest.raises(ValueError, match="weekdays must be"):
        RecurrenceRule(RepeatPeriod.weekly, weekdays=(7,))
    with pytest.raises(ValueError, match="weekdays must be"):
        RecurrenceRule(RepeatPeriod.weekly, weekdays=(-1,))


# --- next_slot_after: period strides ----------------------------------------


def test_next_slot_daily_weekly_preserve_time() -> None:
    base = datetime(2026, 7, 18, 14, 30, tzinfo=UTC)
    assert next_slot_after(base, DAILY, UTC_ZONE) == datetime(2026, 7, 19, 14, 30, tzinfo=UTC)
    assert next_slot_after(base, WEEKLY, UTC_ZONE) == datetime(2026, 7, 25, 14, 30, tzinfo=UTC)


def test_next_slot_applies_the_interval() -> None:
    base = datetime(2026, 7, 18, tzinfo=UTC)
    assert next_slot_after(base, repeating(RepeatPeriod.daily, 3), UTC_ZONE) == datetime(
        2026, 7, 21, tzinfo=UTC
    )
    assert next_slot_after(base, repeating(RepeatPeriod.weekly, 2), UTC_ZONE) == datetime(
        2026, 8, 1, tzinfo=UTC
    )


def test_next_slot_monthly_clamps_day_and_rolls_year() -> None:
    # Jan 31 + 1 month -> Feb 28 (2026 is not a leap year); time-of-day preserved.
    assert next_slot_after(datetime(2026, 1, 31, 9, 0, tzinfo=UTC), MONTHLY, UTC_ZONE) == datetime(
        2026, 2, 28, 9, 0, tzinfo=UTC
    )
    # December rolls into the next year.
    assert next_slot_after(datetime(2026, 12, 15, tzinfo=UTC), MONTHLY, UTC_ZONE) == datetime(
        2027, 1, 15, tzinfo=UTC
    )
    # An interval that clears February keeps the 31st.
    assert next_slot_after(
        datetime(2026, 1, 31, tzinfo=UTC), repeating(RepeatPeriod.monthly, 2), UTC_ZONE
    ) == datetime(2026, 3, 31, tzinfo=UTC)


def test_next_slot_yearly_clamps_leap_day() -> None:
    leap_day = datetime(2028, 2, 29, tzinfo=UTC)
    # Feb 29 + 1 year -> Feb 28.
    assert next_slot_after(leap_day, YEARLY, UTC_ZONE) == datetime(2029, 2, 28, tzinfo=UTC)
    # + 2 years lands on a non-leap year too, so it still clamps.
    assert next_slot_after(leap_day, repeating(RepeatPeriod.yearly, 2), UTC_ZONE) == datetime(
        2030, 2, 28, tzinfo=UTC
    )
    # + 4 years lands on a leap year, so the 29th survives.
    assert next_slot_after(leap_day, repeating(RepeatPeriod.yearly, 4), UTC_ZONE) == datetime(
        2032, 2, 29, tzinfo=UTC
    )


def test_next_slot_manual_raises() -> None:
    with pytest.raises(ValueError, match="no recurrence interval"):
        next_slot_after(datetime(2026, 7, 18, tzinfo=UTC), MANUAL, UTC_ZONE)


# --- next_slot_after: weekday hops ------------------------------------------


def test_next_slot_single_weekday_is_a_whole_week_on() -> None:
    # Tue 21 Jul -> Tue 28 Jul.
    assert next_slot_after(datetime(2026, 7, 21, tzinfo=UTC), weekly_on(TUE), UTC_ZONE) == datetime(
        2026, 7, 28, tzinfo=UTC
    )


def test_next_slot_hops_between_weekdays_within_the_week() -> None:
    rule = weekly_on(TUE, FRI)
    # Tue 21 -> Fri 24 (+3), then Fri 24 -> Tue 28 (+4): twice a week, alternating stride.
    assert next_slot_after(datetime(2026, 7, 21, tzinfo=UTC), rule, UTC_ZONE) == datetime(
        2026, 7, 24, tzinfo=UTC
    )
    assert next_slot_after(datetime(2026, 7, 24, tzinfo=UTC), rule, UTC_ZONE) == datetime(
        2026, 7, 28, tzinfo=UTC
    )
    # Sun 19 is past both selected days, so it wraps to the next week's Tuesday.
    assert next_slot_after(datetime(2026, 7, 19, tzinfo=UTC), rule, UTC_ZONE) == datetime(
        2026, 7, 21, tzinfo=UTC
    )


def test_next_slot_from_an_unselected_weekday_snaps_onto_the_grid() -> None:
    # Wed 22 with only Mondays selected -> Mon 27 (+5): an off-grid row self-heals on its
    # very first step rather than staying off the selected weekdays forever.
    assert next_slot_after(datetime(2026, 7, 22, tzinfo=UTC), weekly_on(MON), UTC_ZONE) == datetime(
        2026, 7, 27, tzinfo=UTC
    )


def test_next_slot_weekdays_can_skip_the_weekend() -> None:
    # Mon-Fri expressed as five weekdays: Fri 24 -> Mon 27, never Sat or Sun.
    weekdays_only = weekly_on(MON, TUE, WED, THU, FRI)
    assert next_slot_after(datetime(2026, 7, 24, tzinfo=UTC), weekdays_only, UTC_ZONE) == datetime(
        2026, 7, 27, tzinfo=UTC
    )


def test_next_slot_adjacent_weekdays_are_one_day_apart() -> None:
    # Sat 18 -> Sun 19 for a weekend chore.
    assert next_slot_after(
        datetime(2026, 7, 18, tzinfo=UTC), weekly_on(SAT, SUN), UTC_ZONE
    ) == datetime(2026, 7, 19, tzinfo=UTC)
    # Sun -> Mon is the smallest step the week-crossing branch can produce (7 - 6 + 0), the
    # ">= 1" boundary that makes every walk over slots terminate.
    assert next_slot_after(datetime(2026, 7, 19, tzinfo=UTC), weekly_on(MON), UTC_ZONE) == datetime(
        2026, 7, 20, tzinfo=UTC
    )


def test_next_slot_interval_is_spent_only_on_crossing_the_week() -> None:
    # The crux of multi-weekday recurrence: hopping Tue -> Fri inside one week is free,
    # and only the Fri -> Tue crossing spends the two-week interval.
    fortnightly = weekly_on(TUE, FRI, every=2)
    assert next_slot_after(datetime(2026, 7, 21, tzinfo=UTC), fortnightly, UTC_ZONE) == datetime(
        2026, 7, 24, tzinfo=UTC
    )  # +3, same week
    assert next_slot_after(datetime(2026, 7, 24, tzinfo=UTC), fortnightly, UTC_ZONE) == datetime(
        2026, 8, 4, tzinfo=UTC
    )  # +11, two weeks on
    # A single weekday has no intra-week hop, so it always spends the interval.
    assert next_slot_after(
        datetime(2026, 7, 20, tzinfo=UTC), weekly_on(MON, every=2), UTC_ZONE
    ) == datetime(2026, 8, 3, tzinfo=UTC)


def test_next_slot_weekday_hop_preserves_time_of_day() -> None:
    assert next_slot_after(
        datetime(2026, 7, 21, 9, 15, tzinfo=UTC), weekly_on(TUE, FRI), UTC_ZONE
    ) == datetime(2026, 7, 24, 9, 15, tzinfo=UTC)


# --- snap_to_slot -----------------------------------------------------------


def test_snap_to_slot_leaves_a_valid_slot_alone_and_is_idempotent() -> None:
    rule = weekly_on(TUE, FRI)
    tuesday = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
    assert snap_to_slot(tuesday, rule, UTC_ZONE) == tuesday
    assert snap_to_slot(snap_to_slot(tuesday, rule, UTC_ZONE), rule, UTC_ZONE) == tuesday


def test_snap_to_slot_moves_forward_to_the_nearest_selected_weekday() -> None:
    # Wed 22 -> Fri 24 (+2), the nearest selected day forward, not backwards to Tuesday.
    assert snap_to_slot(
        datetime(2026, 7, 22, tzinfo=UTC), weekly_on(TUE, FRI), UTC_ZONE
    ) == datetime(2026, 7, 24, tzinfo=UTC)


def test_snap_to_slot_never_spends_the_interval() -> None:
    # Sat 18 -> Tue 21 (+3) even at a four-week interval: snapping re-phases the cycle from
    # the datetime it is given, so pinning weekdays onto a live chore moves its open
    # occurrence by days rather than by weeks.
    assert snap_to_slot(
        datetime(2026, 7, 18, tzinfo=UTC), weekly_on(TUE, every=4), UTC_ZONE
    ) == datetime(2026, 7, 21, tzinfo=UTC)


def test_snap_to_slot_is_identity_for_unpinned_rules() -> None:
    # Only a pinned rule has weekdays to snap to; for the rest (including manual, which
    # reconcile passes when a recurring chore becomes a one-off) any datetime is a
    # legitimate slot because the phase lives in the occurrence chain.
    wednesday = datetime(2026, 7, 22, tzinfo=UTC)
    for rule in (DAILY, WEEKLY, MONTHLY, YEARLY, MANUAL, repeating(RepeatPeriod.weekly, 3)):
        assert snap_to_slot(wednesday, rule, UTC_ZONE) == wednesday


# --- days_until_due / due_status --------------------------------------------


def test_days_until_due_is_date_based_and_normalises_tz() -> None:
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    # Due at 00:00 today is "today" (0), not overdue, despite being in the past.
    assert days_until_due(datetime(2026, 7, 18, 0, 0, tzinfo=UTC), now, UTC_ZONE) == 0
    assert days_until_due(datetime(2026, 7, 4, tzinfo=UTC), now, UTC_ZONE) == -14
    assert days_until_due(datetime(2026, 7, 20, 9, 0, tzinfo=UTC), now, UTC_ZONE) == 2


def test_due_status_buckets() -> None:
    assert due_status(-1) == DueStatus.overdue
    assert due_status(0) == DueStatus.today
    assert due_status(5) == DueStatus.soon


def test_days_since_is_date_based_and_normalises_tz() -> None:
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    # Anything earlier today reads as 0, whatever the time, so "Last done today" holds for
    # a completion at 00:01 and at 11:59 alike.
    assert days_since(datetime(2026, 7, 18, 0, 1, tzinfo=UTC), now, UTC_ZONE) == 0
    assert days_since(datetime(2026, 7, 18, 11, 59, tzinfo=UTC), now, UTC_ZONE) == 0
    assert days_since(datetime(2026, 7, 17, 23, 0, tzinfo=UTC), now, UTC_ZONE) == 1
    assert days_since(datetime(2026, 7, 4, tzinfo=UTC), now, UTC_ZONE) == 14
    # A non-UTC input is normalised, not compared naively: 01:00 in +02:00 is still the
    # 17th in UTC, so this is yesterday rather than today.
    assert (
        days_since(datetime(2026, 7, 18, 1, 0, tzinfo=timezone(timedelta(hours=2))), now, UTC_ZONE)
        == 1
    )


# --- advance_anchor (schedule-anchored recurrence) ------------------------


def test_advance_anchor_early_completion_advances_one_interval() -> None:
    # Completing tomorrow's occurrence today keeps it on the grid: next is the day
    # after tomorrow, not tomorrow again (the original bug).
    anchor = advance_anchor(
        datetime(2026, 7, 21, tzinfo=UTC),  # due tomorrow
        datetime(2026, 7, 20, 9, 0, tzinfo=UTC),  # completed today
        DAILY,
        UTC_ZONE,
    )
    assert anchor == datetime(2026, 7, 21, tzinfo=UTC)
    assert next_slot_after(anchor, DAILY, UTC_ZONE) == datetime(2026, 7, 22, tzinfo=UTC)


def test_advance_anchor_on_time_completion_advances_to_next_day() -> None:
    anchor = advance_anchor(
        datetime(2026, 7, 20, tzinfo=UTC),  # due today
        datetime(2026, 7, 20, 14, 0, tzinfo=UTC),  # completed today
        DAILY,
        UTC_ZONE,
    )
    assert anchor == datetime(2026, 7, 20, tzinfo=UTC)
    assert next_slot_after(anchor, DAILY, UTC_ZONE) == datetime(2026, 7, 21, tzinfo=UTC)


def test_advance_anchor_overdue_by_one_lands_tomorrow_not_today() -> None:
    # A chore due yesterday, completed today, is next due tomorrow (not today).
    anchor = advance_anchor(
        datetime(2026, 7, 19, tzinfo=UTC),  # due yesterday
        datetime(2026, 7, 20, 8, 0, tzinfo=UTC),  # completed today
        DAILY,
        UTC_ZONE,
    )
    assert anchor == datetime(2026, 7, 20, tzinfo=UTC)
    assert next_slot_after(anchor, DAILY, UTC_ZONE) == datetime(2026, 7, 21, tzinfo=UTC)


def test_advance_anchor_missed_a_week_skips_backlog_to_tomorrow() -> None:
    # A daily chore ignored for a week clears in one completion: next due tomorrow,
    # the missed days are skipped rather than backfilled.
    anchor = advance_anchor(
        datetime(2026, 7, 13, tzinfo=UTC),  # due a week ago
        datetime(2026, 7, 20, 12, 0, tzinfo=UTC),  # completed today
        DAILY,
        UTC_ZONE,
    )
    assert anchor == datetime(2026, 7, 20, tzinfo=UTC)
    assert next_slot_after(anchor, DAILY, UTC_ZONE) == datetime(2026, 7, 21, tzinfo=UTC)


def test_advance_anchor_weekly_overdue_preserves_weekday() -> None:
    # A weekly chore completed late on a different weekday stays on its original
    # weekday grid instead of jumping to the completion weekday.
    scheduled = datetime(2026, 6, 29, tzinfo=UTC)
    anchor = advance_anchor(
        scheduled,
        datetime(2026, 7, 15, 10, 0, tzinfo=UTC),  # a later, different weekday
        WEEKLY,
        UTC_ZONE,
    )
    # Last weekly slot on or before the completion date, still on the same weekday.
    assert anchor == datetime(2026, 7, 13, tzinfo=UTC)
    assert anchor.weekday() == scheduled.weekday()
    assert next_slot_after(anchor, WEEKLY, UTC_ZONE) == datetime(2026, 7, 20, tzinfo=UTC)


def test_advance_anchor_monthly_overdue_stays_on_day_of_month() -> None:
    anchor = advance_anchor(
        datetime(2026, 1, 15, tzinfo=UTC), datetime(2026, 3, 10, tzinfo=UTC), MONTHLY, UTC_ZONE
    )
    assert anchor == datetime(2026, 2, 15, tzinfo=UTC)
    assert next_slot_after(anchor, MONTHLY, UTC_ZONE) == datetime(2026, 3, 15, tzinfo=UTC)


def test_advance_anchor_normalises_away_completion_time_of_day() -> None:
    # The completion time-of-day must not leak into the anchor: a midnight-grid
    # occurrence completed at 23:59 stays on the midnight grid (no drift).
    anchor = advance_anchor(
        datetime(2026, 7, 18, tzinfo=UTC),
        datetime(2026, 7, 20, 23, 59, tzinfo=UTC),
        DAILY,
        UTC_ZONE,
    )
    assert anchor == datetime(2026, 7, 20, tzinfo=UTC)
    assert (anchor.hour, anchor.minute) == (0, 0)


def test_advance_anchor_manual_returns_scheduled_for() -> None:
    # An unscheduled chore has no grid to roll forward on, so its slot stands. Unreachable
    # from next_occurrence_after (which handles `manual` itself), but the guard is what
    # keeps a direct call off next_slot_after's ValueError.
    scheduled = datetime(2026, 7, 20, tzinfo=UTC)
    assert (
        advance_anchor(scheduled, datetime(2026, 7, 25, tzinfo=UTC), MANUAL, UTC_ZONE) == scheduled
    )


def test_advance_anchor_keeps_the_cycle_phase_over_a_long_gap() -> None:
    # Every other Tuesday, scheduled Tue 7 Jul, left until Fri 7 Aug. The anchor walks the
    # chain (21 Jul, 4 Aug) rather than jumping at the completion date, so the successor
    # stays on the original fortnightly phase: 18 Aug, not 11 Aug.
    anchor = advance_anchor(
        datetime(2026, 7, 7, tzinfo=UTC),
        datetime(2026, 8, 7, 10, 0, tzinfo=UTC),
        weekly_on(TUE, every=2),
        UTC_ZONE,
    )
    assert anchor == datetime(2026, 8, 4, tzinfo=UTC)
    # The successor is the point of the test: collapsing the walk into a single "first slot
    # after the completion date" call would give 11 Aug, off the original phase.
    assert next_slot_after(anchor, weekly_on(TUE, every=2), UTC_ZONE) == datetime(
        2026, 8, 18, tzinfo=UTC
    )


# --- occurrence helpers (materialised model) --------------------------------


def test_first_occurrence_is_start_date_midnight_utc() -> None:
    assert first_occurrence(date(2026, 7, 10), WEEKLY, UTC_ZONE) == datetime(
        2026, 7, 10, tzinfo=UTC
    )
    assert first_occurrence(date(2026, 7, 10), MONTHLY, UTC_ZONE) == datetime(
        2026, 7, 10, tzinfo=UTC
    )


def test_first_occurrence_snaps_forward_to_a_selected_weekday() -> None:
    rule = weekly_on(TUE, FRI)
    # Mon 20 -> Tue 21, the first selected day on or after the start date.
    assert first_occurrence(date(2026, 7, 20), rule, UTC_ZONE) == datetime(2026, 7, 21, tzinfo=UTC)
    # Wed 22 -> Fri 24: forward only, never back to Tuesday.
    assert first_occurrence(date(2026, 7, 22), rule, UTC_ZONE) == datetime(2026, 7, 24, tzinfo=UTC)
    # Fri 24 already qualifies, so it is kept.
    assert first_occurrence(date(2026, 7, 24), rule, UTC_ZONE) == datetime(2026, 7, 24, tzinfo=UTC)


def test_first_occurrence_snap_does_not_wait_out_the_interval() -> None:
    # Sat 18 with "every two weeks on Tuesday" is due Tue 21, three days later. A
    # start-date-anchored lattice would have made this 10 days out (its own week's Tuesday
    # is already past, and the following week is the wrong parity), which is why the grid
    # is walked from the previous slot instead.
    assert first_occurrence(date(2026, 7, 18), weekly_on(TUE, every=2), UTC_ZONE) == datetime(
        2026, 7, 21, tzinfo=UTC
    )


def test_next_occurrence_after_early_completion_advances_one_interval() -> None:
    # Completing tomorrow's occurrence today: the successor is the day after tomorrow.
    assert next_occurrence_after(
        datetime(2026, 7, 21, tzinfo=UTC),  # due tomorrow
        datetime(2026, 7, 20, 9, 0, tzinfo=UTC),  # completed today
        DAILY,
        UTC_ZONE,
    ) == datetime(2026, 7, 22, tzinfo=UTC)


def test_next_occurrence_after_overdue_skips_backlog_to_tomorrow() -> None:
    # A daily chore a week overdue clears to tomorrow, missed days skipped not backfilled.
    assert next_occurrence_after(
        datetime(2026, 7, 13, tzinfo=UTC), datetime(2026, 7, 20, 12, 0, tzinfo=UTC), DAILY, UTC_ZONE
    ) == datetime(2026, 7, 21, tzinfo=UTC)


def test_next_occurrence_after_weekly_preserves_weekday() -> None:
    scheduled = datetime(2026, 6, 29, tzinfo=UTC)  # a Monday
    nxt = next_occurrence_after(
        scheduled, datetime(2026, 7, 15, 10, 0, tzinfo=UTC), WEEKLY, UTC_ZONE
    )
    assert nxt == datetime(2026, 7, 20, tzinfo=UTC)
    assert nxt.weekday() == scheduled.weekday()


def test_next_occurrence_after_monthly_clamps_day_of_month() -> None:
    # Jan 31 completed on time -> next is Feb 28 (day clamped), staying on the grid.
    assert next_occurrence_after(
        datetime(2026, 1, 31, tzinfo=UTC),
        datetime(2026, 1, 31, 9, 0, tzinfo=UTC),
        MONTHLY,
        UTC_ZONE,
    ) == datetime(2026, 2, 28, tzinfo=UTC)


def test_next_occurrence_after_manual_reopens_at_the_completion_moment() -> None:
    # An unscheduled chore is repeatable on demand, so it reopens immediately, anchored at
    # the completion moment rather than stepping any grid. Interval and weekdays are set
    # here to prove they are ignored (RecurrenceRule.of drops the weekdays anyway).
    completed_at = datetime(2026, 7, 25, 14, 37, tzinfo=UTC)
    assert (
        next_occurrence_after(
            datetime(2026, 7, 20, tzinfo=UTC),
            completed_at,
            RecurrenceRule.of(RepeatPeriod.manual, 3, [TUE, FRI]),
            UTC_ZONE,
        )
        == completed_at
    )


def test_next_occurrence_after_manual_keeps_the_time_of_day() -> None:
    # The full timestamp, NOT its midnight: uq_occurrence_chore_scheduled is per
    # (chore, scheduled_for), so a date would collide the second time an unscheduled chore
    # was done in one day. Two same-day completions must yield two distinct slots.
    morning = datetime(2026, 7, 25, 8, 0, tzinfo=UTC)
    evening = datetime(2026, 7, 25, 20, 0, tzinfo=UTC)
    first = next_occurrence_after(datetime(2026, 7, 20, tzinfo=UTC), morning, MANUAL, UTC_ZONE)
    second = next_occurrence_after(first, evening, MANUAL, UTC_ZONE)
    assert first != second
    assert (first, second) == (morning, evening)


# --- occurrence helpers: intervals and pinned weekdays ----------------------


def test_next_occurrence_after_garbage_on_tuesdays_skips_the_backlog() -> None:
    # "We take out the garbage on Tuesday", neglected for three weeks and finally done on
    # Sat 25 Jul: due the coming Tuesday (28th), with the missed Tuesdays skipped.
    nxt = next_occurrence_after(
        datetime(2026, 7, 7, tzinfo=UTC),
        datetime(2026, 7, 25, 11, 0, tzinfo=UTC),
        weekly_on(TUE),
        UTC_ZONE,
    )
    assert nxt == datetime(2026, 7, 28, tzinfo=UTC)
    assert nxt.weekday() == TUE


def test_next_occurrence_after_twice_a_week_alternates() -> None:
    # "We start the washing machine on Tuesday and on Friday": completing the Tuesday slot
    # yields the Friday, and completing that yields the following Tuesday.
    rule = weekly_on(TUE, FRI)
    friday = datetime(2026, 7, 24, tzinfo=UTC)
    assert (
        next_occurrence_after(
            datetime(2026, 7, 21, tzinfo=UTC),
            datetime(2026, 7, 21, 19, 0, tzinfo=UTC),
            rule,
            UTC_ZONE,
        )
        == friday
    )
    assert next_occurrence_after(
        friday, datetime(2026, 7, 24, 19, 0, tzinfo=UTC), rule, UTC_ZONE
    ) == datetime(2026, 7, 28, tzinfo=UTC)


def test_next_occurrence_after_twice_a_week_early_completion_takes_the_other_day() -> None:
    # Tuesday's slot done early on Monday goes to Friday, not back round to Tuesday.
    assert next_occurrence_after(
        datetime(2026, 7, 21, tzinfo=UTC),
        datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
        weekly_on(TUE, FRI),
        UTC_ZONE,
    ) == datetime(2026, 7, 24, tzinfo=UTC)


def test_next_occurrence_after_twice_a_week_overdue_lands_on_the_next_selected_day() -> None:
    # Three weeks behind on the Tuesday slot, caught up on Wed 29 Jul -> Fri 31 Jul.
    assert next_occurrence_after(
        datetime(2026, 7, 7, tzinfo=UTC),
        datetime(2026, 7, 29, 20, 0, tzinfo=UTC),
        weekly_on(TUE, FRI),
        UTC_ZONE,
    ) == datetime(2026, 7, 31, tzinfo=UTC)


def test_next_occurrence_after_every_two_days_keeps_its_parity() -> None:
    # "We run the dishwasher every 2 days", started Mon 13 Jul, so the grid is the odd
    # days. Done early -> +2; a week behind -> the first grid day after the completion.
    every_other_day = repeating(RepeatPeriod.daily, 2)
    assert next_occurrence_after(
        datetime(2026, 7, 21, tzinfo=UTC),
        datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
        every_other_day,
        UTC_ZONE,
    ) == datetime(2026, 7, 23, tzinfo=UTC)
    assert next_occurrence_after(
        datetime(2026, 7, 13, tzinfo=UTC),
        datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        every_other_day,
        UTC_ZONE,
    ) == datetime(2026, 7, 21, tzinfo=UTC)


def test_next_occurrence_after_fortnightly_two_weekdays() -> None:
    # Every other Tue+Fri: +3 within the week, +11 across it.
    rule = weekly_on(TUE, FRI, every=2)
    assert next_occurrence_after(
        datetime(2026, 7, 21, tzinfo=UTC), datetime(2026, 7, 21, 9, 0, tzinfo=UTC), rule, UTC_ZONE
    ) == datetime(2026, 7, 24, tzinfo=UTC)
    assert next_occurrence_after(
        datetime(2026, 7, 24, tzinfo=UTC), datetime(2026, 7, 24, 9, 0, tzinfo=UTC), rule, UTC_ZONE
    ) == datetime(2026, 8, 4, tzinfo=UTC)


def test_next_occurrence_after_quarterly_skips_whole_quarters() -> None:
    # Every 3 months from 15 Jan, eight months late: whole quarters are skipped and the
    # day-of-month survives.
    assert next_occurrence_after(
        datetime(2026, 1, 15, tzinfo=UTC),
        datetime(2026, 9, 10, tzinfo=UTC),
        repeating(RepeatPeriod.monthly, 3),
        UTC_ZONE,
    ) == datetime(2026, 10, 15, tzinfo=UTC)


def test_next_occurrence_after_off_grid_row_self_heals() -> None:
    # An occurrence left on a Wednesday by an edit that pinned Tue+Fri moves onto the
    # selected weekdays as soon as it is completed.
    assert next_occurrence_after(
        datetime(2026, 7, 22, tzinfo=UTC),
        datetime(2026, 7, 22, 18, 0, tzinfo=UTC),
        weekly_on(TUE, FRI),
        UTC_ZONE,
    ) == datetime(2026, 7, 24, tzinfo=UTC)
    # With an interval the two routes onto the grid diverge, so pin the one taken here:
    # completing an off-grid Wednesday crosses the week boundary and so spends the
    # interval (+13, to Tue 4 Aug). Only `snap_to_slot`, which the edit path uses, moves
    # the shorter +6 without spending it.
    assert next_occurrence_after(
        datetime(2026, 7, 22, tzinfo=UTC),
        datetime(2026, 7, 22, 18, 0, tzinfo=UTC),
        weekly_on(TUE, every=2),
        UTC_ZONE,
    ) == datetime(2026, 8, 4, tzinfo=UTC)
    assert snap_to_slot(
        datetime(2026, 7, 22, tzinfo=UTC), weekly_on(TUE, every=2), UTC_ZONE
    ) == datetime(2026, 7, 28, tzinfo=UTC)

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.core.chores import DueStatus, days_late, days_until_due, due_status
from app.core.households import member_household_ids
from app.models import Chore, ChoreOccurrence, HouseholdRole, OccurrenceStatus, RepeatPeriod, User
from app.schemas.stats import (
    CompletionBucket,
    PersonStat,
    Punctuality,
    StatsKpis,
    StatsRead,
    StatusBreakdown,
)

router = APIRouter()

StatsRange = Literal["7d", "30d", "90d"]
RANGE_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}
# Ranges longer than this bucket the time chart by week instead of by day, so the
# 90-day view stays ~13 bars rather than 90.
WEEKLY_ABOVE_DAYS = 30


def _week_start(day: date) -> date:
    """The Monday on or before `day` (ISO week start)."""
    return day - timedelta(days=day.weekday())


@router.get("", response_model=StatsRead)
async def get_stats(
    user: CurrentUser,
    session: SessionDep,
    time_range: Annotated[StatsRange, Query(alias="range")] = "30d",
    household_id: Annotated[int | None, Query(ge=1)] = None,
    user_id: Annotated[int | None, Query(ge=1)] = None,
) -> StatsRead:
    """Aggregated completion and overdue statistics across the active households where the
    caller is at least a deputy (so housemates' work is included), for the Statistics page.

    `range` (7d/30d/90d) windows the completion-based metrics; the overdue snapshot
    (`status_breakdown`, `currently_overdue`, `active_chores`) is always live. Optional
    `household_id` narrows to one household; `user_id` narrows completions to that
    person's credited completions and the live snapshot to occurrences currently on
    their plate. A household/person the user can't see just yields empty scope, and so does a
    household they are only a helper in - a helper is not shown other people's numbers, and
    the page spans every household at once, so narrowing the scope is what enforces that
    rather than a 403.

    Unscheduled chores have no deadline, so they are counted where the question is "how much
    got done, and by whom" (`completed_in_range`, `completions_over_time`, `per_person`) and
    excluded where the answer needs a due date (`currently_overdue`, `status_breakdown`,
    `active_chores`, `punctuality`, `on_time_rate`). One consequence to keep in mind:
    `punctuality` therefore does not sum to `completed_in_range`.

    Skipped occurrences are closures that produced no work, so every "work done" metric here
    excludes them and they are reported alongside instead: `skipped_in_range`, a per-bucket
    `skipped` on `completions_over_time`, and a fourth `punctuality` bucket. Two notes on that
    last one. It is the one place the two exclusions meet, and it is not a special case: skips
    are counted inside the same `repeats != manual` branch as the three due-date buckets, so
    the four together are exactly the scheduled occurrences that closed in the range. And
    `on_time_rate` deliberately does NOT count skips in its denominator, staying "of the work
    that was done, how much was punctual" - so the four buckets do not add up to that rate's
    base either."""
    now = datetime.now(UTC)
    today = now.date()
    # UTC day bounds (not a ::date cast, which depends on the session TimeZone), matching
    # the Home endpoint's convention.
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    tomorrow_start = today_start + timedelta(days=1)
    range_days = RANGE_DAYS[time_range]
    start_date = today - timedelta(days=range_days - 1)
    range_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=UTC)
    weekly = range_days > WEEKLY_ABOVE_DAYS
    granularity = "week" if weekly else "day"

    scope = Chore.household_id.in_(member_household_ids(user.id, HouseholdRole.deputy))

    # --- Live snapshot: the open occurrences (range-independent) ---
    # Soft-deleted chores drop out here (nothing left to do), matching the Home scope;
    # completed history below is intentionally kept even for soft-deleted chores.
    # Unscheduled chores drop out too: with no due date they cannot be overdue, due today or
    # upcoming, so they have no bucket to land in. This single predicate is what keeps them
    # out of `status_breakdown`, `currently_overdue` AND `active_chores`, which all read the
    # same list - and it preserves the invariant that the three buckets sum to
    # `active_chores`, which excluding them from only the overdue count would have broken.
    open_filters = [
        Chore.deleted_at.is_(None),
        scope,
        Chore.repeats != RepeatPeriod.manual,
        ChoreOccurrence.status == OccurrenceStatus.open,
    ]
    if household_id is not None:
        open_filters.append(Chore.household_id == household_id)
    if user_id is not None:
        # For the live view, "this person" means whose turn it is now (the assignee).
        open_filters.append(ChoreOccurrence.assignee_id == user_id)
    open_due = (
        (
            await session.execute(
                select(ChoreOccurrence.scheduled_for)
                .join(Chore, Chore.id == ChoreOccurrence.chore_id)
                .where(*open_filters)
            )
        )
        .scalars()
        .all()
    )
    status_counts = {DueStatus.overdue: 0, DueStatus.today: 0, DueStatus.soon: 0}
    for scheduled_for in open_due:
        status_counts[due_status(days_until_due(scheduled_for, now))] += 1
    status_breakdown = StatusBreakdown(
        overdue=status_counts[DueStatus.overdue],
        today=status_counts[DueStatus.today],
        soon=status_counts[DueStatus.soon],
    )

    # --- Closures within the range ---
    # Completions and skips come back in one pass (they are the same kind of row) and the loop
    # below splits them; only the punctuality breakdown needs them side by side, but a second
    # query for the sake of it would double the scan.
    done_filters = [
        scope,
        ChoreOccurrence.status == OccurrenceStatus.done,
        ChoreOccurrence.completed_at >= range_start,
        ChoreOccurrence.completed_at < tomorrow_start,
    ]
    if household_id is not None:
        done_filters.append(Chore.household_id == household_id)
    if user_id is not None:
        # For completions, "this person" means who got the credit.
        done_filters.append(ChoreOccurrence.completed_by_user_id == user_id)
    done_rows = (
        await session.execute(
            select(
                ChoreOccurrence.completed_at,
                ChoreOccurrence.scheduled_for,
                ChoreOccurrence.skipped,
                # Punctuality is only meaningful against a deadline, so the period rides
                # along to exclude the unscheduled ones from it (see the loop below).
                Chore.repeats,
                User.id,
                User.first_name,
                User.last_name,
            )
            .join(Chore, Chore.id == ChoreOccurrence.chore_id)
            # Completer may be NULL (a hard-deleted user); such rows still count in the
            # totals but are dropped from the per-person breakdown below.
            .outerjoin(User, User.id == ChoreOccurrence.completed_by_user_id)
            .where(*done_filters)
        )
    ).all()

    # Pre-seed every bucket to 0 so the chart has a continuous axis over the range. Both
    # series get the same keys, so the stacked bars line up even where one of them is empty.
    bucket_keys: list[date] = []
    if weekly:
        cursor, last = _week_start(start_date), _week_start(today)
        while cursor <= last:
            bucket_keys.append(cursor)
            cursor += timedelta(days=7)
    else:
        bucket_keys = [start_date + timedelta(days=offset) for offset in range(range_days)]
    done_buckets: dict[date, int] = dict.fromkeys(bucket_keys, 0)
    skipped_buckets: dict[date, int] = dict.fromkeys(bucket_keys, 0)

    on_time = late = early = skipped = 0
    total = skipped_total = 0
    # user_id -> [first_name, last_name, count]
    person_counts: dict[int, list] = {}
    for completed_at, scheduled_for, was_skipped, repeats, uid, first_name, last_name in done_rows:
        completed_day = completed_at.astimezone(UTC).date()
        key = _week_start(completed_day) if weekly else completed_day
        # A skip closed the slot but produced nothing, so it is kept out of every count that
        # measures work: the headline total, the done series, and the per-person ranking. It
        # gets its own series and its own KPI instead.
        if was_skipped:
            skipped_total += 1
            skipped_buckets[key] = skipped_buckets.get(key, 0) + 1
        else:
            total += 1
            done_buckets[key] = done_buckets.get(key, 0) + 1
            if uid is not None:
                entry = person_counts.setdefault(uid, [first_name, last_name, 0])
                entry[2] += 1
        # Doing an unscheduled chore is still work done, so it counts towards the total, the
        # time chart and the per-person ranking. It just cannot be punctual: its slot records
        # when the chore became available, not a deadline, so measuring lateness against it
        # would score the gap since the last completion as being late. A skip is the mirror
        # image: it had a real deadline (skipping an unscheduled chore is refused outright, see
        # skip_chore), and what it lacks is the work. So the two exclusions meet here, and the
        # four buckets below are exactly the scheduled occurrences closed in the range.
        if repeats != RepeatPeriod.manual:
            if was_skipped:
                skipped += 1
            else:
                late_by = days_late(scheduled_for, completed_at)
                if late_by > 0:
                    late += 1
                elif late_by < 0:
                    early += 1
                else:
                    on_time += 1

    # The punctuality denominator is the scheduled completions only, NOT `total` and not the
    # four buckets: it differs from the first by however many unscheduled chores were done in
    # the range, and from the second by the skips, which are closures rather than work.
    scheduled_total = on_time + late + early
    # Over the union of both series' keys, reading each with `.get`. The invariant is that the
    # query's window and the seeding above agree, so every key lands in both dicts; the writes
    # deliberately do not depend on it (`.get(key, 0) + 1`) and neither does this, so a bucket
    # outside the seeded axis shows up as an extra point rather than a KeyError or a silently
    # dropped count. Cheaper to keep symmetrical than to prove the invariant on every edit.
    completions_over_time = [
        CompletionBucket(
            bucket=day.isoformat(),
            count=done_buckets.get(day, 0),
            skipped=skipped_buckets.get(day, 0),
        )
        for day in sorted(done_buckets.keys() | skipped_buckets.keys())
    ]
    # Ranked most-completions-first, then by name for a stable order on ties.
    per_person = sorted(
        (
            PersonStat(user_id=uid, first_name=first, last_name=last, count=count)
            for uid, (first, last, count) in person_counts.items()
        ),
        key=lambda p: (-p.count, p.first_name, p.last_name, p.user_id),
    )

    return StatsRead(
        range=time_range,
        granularity=granularity,
        kpis=StatsKpis(
            completed_in_range=total,
            skipped_in_range=skipped_total,
            currently_overdue=status_breakdown.overdue,
            # Fraction not late (on time or early) of the completions that had a deadline;
            # None when none of them did, which includes "nothing was completed at all".
            on_time_rate=(on_time + early) / scheduled_total if scheduled_total else None,
            active_chores=len(open_due),
        ),
        completions_over_time=completions_over_time,
        status_breakdown=status_breakdown,
        punctuality=Punctuality(on_time=on_time, late=late, early=early, skipped=skipped),
        per_person=per_person,
    )

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.core.chores import DueStatus, days_late, days_until_due, due_status
from app.core.households import member_household_ids
from app.models import Chore, ChoreOccurrence, OccurrenceStatus, User
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
    """Aggregated completion and overdue statistics across the user's active
    households (so housemates' work is included), for the Statistics page.

    `range` (7d/30d/90d) windows the completion-based metrics; the overdue snapshot
    (`status_breakdown`, `currently_overdue`, `active_chores`) is always live. Optional
    `household_id` narrows to one household; `user_id` narrows completions to that
    person's credited completions and the live snapshot to occurrences currently on
    their plate. A household/person the user can't see just yields empty scope."""
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

    scope = Chore.household_id.in_(member_household_ids(user.id))

    # --- Live snapshot: the open occurrences (range-independent) ---
    # Soft-deleted chores drop out here (nothing left to do), matching the Home scope;
    # completed history below is intentionally kept even for soft-deleted chores.
    open_filters = [
        Chore.deleted_at.is_(None),
        scope,
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

    # --- Completions within the range ---
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

    # Pre-seed every bucket to 0 so the chart has a continuous axis over the range.
    buckets: dict[date, int] = {}
    if weekly:
        cursor, last = _week_start(start_date), _week_start(today)
        while cursor <= last:
            buckets[cursor] = 0
            cursor += timedelta(days=7)
    else:
        for offset in range(range_days):
            buckets[start_date + timedelta(days=offset)] = 0

    on_time = late = early = 0
    # user_id -> [first_name, last_name, count]
    person_counts: dict[int, list] = {}
    for completed_at, scheduled_for, uid, first_name, last_name in done_rows:
        completed_day = completed_at.astimezone(UTC).date()
        key = _week_start(completed_day) if weekly else completed_day
        buckets[key] = buckets.get(key, 0) + 1
        late_by = days_late(scheduled_for, completed_at)
        if late_by > 0:
            late += 1
        elif late_by < 0:
            early += 1
        else:
            on_time += 1
        if uid is not None:
            entry = person_counts.setdefault(uid, [first_name, last_name, 0])
            entry[2] += 1

    total = len(done_rows)
    completions_over_time = [
        CompletionBucket(bucket=day.isoformat(), count=count)
        for day, count in sorted(buckets.items())
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
            currently_overdue=status_breakdown.overdue,
            # Fraction not late (on time or early); None when nothing was completed.
            on_time_rate=(on_time + early) / total if total else None,
            active_chores=len(open_due),
        ),
        completions_over_time=completions_over_time,
        status_breakdown=status_breakdown,
        punctuality=Punctuality(on_time=on_time, late=late, early=early),
        per_person=per_person,
    )

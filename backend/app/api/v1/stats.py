from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from sqlalchemy import and_, false, or_, select

from app.api.deps import CurrentUser, SessionDep
from app.core import clock
from app.core.chores import DueStatus, days_late, days_until_due, due_status, local_day_bounds
from app.core.households import household_zone, member_household_ids, zones_in_scope
from app.core.occurrences import closure_zone
from app.models import (
    Chore,
    ChoreOccurrence,
    Household,
    HouseholdRole,
    OccurrenceStatus,
    RepeatPeriod,
    User,
)
from app.schemas.stats import (
    CompletionBucket,
    PersonStat,
    Punctuality,
    SkippedChoreStat,
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

# How many chores the most-skipped ranking returns. A product decision - the card is a
# glanceable shortlist, not a table - so a constant like MAX_PENDING_INVITATIONS and
# LOG_RETENTION rather than a Settings field or a query parameter.
MOST_SKIPPED_LIMIT = 5

# The floor the chart axis falls back to when the caller reaches deputy in no household, so the
# series stays a zero-seeded range rather than an empty array. See `axis_windows` below.
UTC_ZONE = ZoneInfo("UTC")


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
    base either.

    `most_skipped` is the one skip figure here that answers *which* chore rather than how
    many, so it is also the one that drops soft-deleted chores: it is a shortlist to act on,
    and a deleted chore cannot be. Their skips do still count in `skipped_in_range`, so the
    ranking deliberately does not sum to that KPI."""
    now = clock.now()
    range_days = RANGE_DAYS[time_range]
    weekly = range_days > WEEKLY_ABOVE_DAYS
    granularity = "week" if weekly else "day"

    # A day starts at a different instant in each household, so both the range window and the
    # bucket a completion lands in are per-household questions. The zones are collected once
    # and drive three things below: the ORed range window, the per-row bucket key, and the
    # width of the pre-seeded axis. `min_role` mirrors the `scope` predicate so the grouping
    # cannot name a household the surrounding query drops.
    zones = await zones_in_scope(session, user.id, household_id, HouseholdRole.deputy)

    def range_window(tz: ZoneInfo) -> tuple[datetime, datetime]:
        """(range start, tomorrow start) in one zone. `- timedelta(days=n)` on an aware datetime
        is wall-clock arithmetic, so this really is n *local* days however many DST transitions
        it spans."""
        day_start, day_end = local_day_bounds(now, tz)
        return day_start - timedelta(days=range_days - 1), day_end

    windows = {tz: range_window(tz) for tz in zones}

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
    # The household's zone rides along so each slot can be judged against its own household's
    # day. Without it this query knew only *when* a chore was due, never *where*, which is not
    # enough to say whether "due today" means today.
    #
    # Read off a joined row rather than looked up in a dict keyed from `zones`. The two sets are
    # identical by construction, but only within one statement: the session is READ COMMITTED,
    # so a caller promoted to deputy in another household between `zones_in_scope` and here
    # would land an id the dict never saw, and a subscript would 500 the page. Joining makes the
    # mismatch unrepresentable and matches what home.py and unscheduled.py already do.
    open_due = (
        await session.execute(
            select(ChoreOccurrence.scheduled_for, Household.timezone)
            .join(Chore, Chore.id == ChoreOccurrence.chore_id)
            .join(Household, Household.id == Chore.household_id)  # to-one: no row multiplication
            .where(*open_filters)
        )
    ).all()
    status_counts = {DueStatus.overdue: 0, DueStatus.today: 0, DueStatus.soon: 0}
    for scheduled_for, zone_name in open_due:
        tz = household_zone(zone_name)
        status_counts[due_status(days_until_due(scheduled_for, now, tz))] += 1
    status_breakdown = StatusBreakdown(
        overdue=status_counts[DueStatus.overdue],
        today=status_counts[DueStatus.today],
        soon=status_counts[DueStatus.soon],
    )

    # --- Closures within the range ---
    # Completions and skips come back in one pass (they are the same kind of row) and the loop
    # below splits them; only the punctuality breakdown needs them side by side, but a second
    # query for the sake of it would double the scan.
    #
    # One window per zone, ORed, as on Home: the last 30 days in Auckland is not the last 30
    # days in Amsterdam. See there for why the `false()` seed rather than a bare `or_()`.
    done_filters = [
        scope,
        ChoreOccurrence.status == OccurrenceStatus.done,
        or_(
            false(),
            *[
                and_(
                    Chore.household_id.in_(ids),
                    ChoreOccurrence.completed_at >= windows[tz][0],
                    ChoreOccurrence.completed_at < windows[tz][1],
                )
                for tz, ids in zones.items()
            ],
        ),
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
                # Which day this closure belongs to, for the bucket key and for lateness. Both
                # are calendar judgements about the past, so both read the zone snapshotted when
                # the row closed rather than wherever the household is now - otherwise moving a
                # household re-buckets and re-scores work nobody touched. The household's zone
                # rides along as the fallback for rows closed before that column existed.
                ChoreOccurrence.completed_timezone,
                Household.timezone,
                User.id,
                User.first_name,
                User.last_name,
                # For the most-skipped ranking: which chore, what it is called *now* (a
                # rename should not split one chore into two rows), and where. `deleted_at`
                # rides along to be branched on in the loop rather than filtered here - see
                # the ranking's own comment below for why it must not join `done_filters`.
                Chore.id,
                Chore.title,
                Household.name,
                Chore.deleted_at,
            )
            .join(Chore, Chore.id == ChoreOccurrence.chore_id)
            .join(Household, Household.id == Chore.household_id)  # to-one: no row multiplication
            # Completer may be NULL (a hard-deleted user); such rows still count in the
            # totals but are dropped from the per-person breakdown below.
            .outerjoin(User, User.id == ChoreOccurrence.completed_by_user_id)
            .where(*done_filters)
        )
    ).all()

    # Pre-seed every bucket to 0 so the chart has a continuous axis over the range. Both
    # series get the same keys, so the stacked bars line up even where one of them is empty.
    #
    # Seeded over the union of the per-zone ranges rather than one of them, so a user whose
    # households straddle the date line gets a continuous axis instead of a hole at whichever
    # end the other zone reaches further. Usually one zone, so usually exactly `range_days`
    # buckets.
    #
    # `windows` can legitimately be empty - a user in no household, but also a **helper-only**
    # one, who reaches deputy nowhere and gets a 200 with nothing in it ("reads narrow, writes
    # 403"). They must still get a zero-seeded axis rather than `[]`: the chart is handed
    # straight to recharts, so an empty array renders as blank space instead of a flat line.
    # UTC is the floor for that, chosen because it is the one zone that needs no household to
    # justify it - it only ever shapes the axis, never which rows are counted, since the query
    # above still matches nothing.
    axis_windows = windows or {UTC_ZONE: range_window(UTC_ZONE)}
    first_day = min(start.astimezone(tz).date() for tz, (start, _) in axis_windows.items())
    # `axis_windows` holds the *exclusive* end (tomorrow's local midnight), so step back a day
    # to get the last day the axis actually covers.
    last_day = max(end.astimezone(tz).date() for tz, (_, end) in axis_windows.items()) - timedelta(
        days=1
    )
    bucket_keys: list[date] = []
    if weekly:
        cursor, last = _week_start(first_day), _week_start(last_day)
        while cursor <= last:
            bucket_keys.append(cursor)
            cursor += timedelta(days=7)
    else:
        cursor = first_day
        while cursor <= last_day:
            bucket_keys.append(cursor)
            cursor += timedelta(days=1)
    done_buckets: dict[date, int] = dict.fromkeys(bucket_keys, 0)
    skipped_buckets: dict[date, int] = dict.fromkeys(bucket_keys, 0)

    on_time = late = early = skipped = 0
    total = skipped_total = 0
    # user_id -> [first_name, last_name, count]
    person_counts: dict[int, list] = {}
    # chore_id -> [title, household_name, count]. Keyed on the chore rather than on its title
    # so a rename mid-range keeps one row, and only ever written to for a skip, which is what
    # makes "count > 0" true by construction rather than by a filter.
    skip_counts: dict[int, list] = {}
    for (
        completed_at,
        scheduled_for,
        was_skipped,
        repeats,
        closed_in,
        household_tz,
        uid,
        first_name,
        last_name,
        chore_id,
        chore_title,
        household_name,
        chore_deleted_at,
    ) in done_rows:
        tz = closure_zone(closed_in, household_tz)
        completed_day = completed_at.astimezone(tz).date()
        key = _week_start(completed_day) if weekly else completed_day
        # A skip closed the slot but produced nothing, so it is kept out of every count that
        # measures work: the headline total, the done series, and the per-person ranking. It
        # gets its own series and its own KPI instead.
        if was_skipped:
            skipped_total += 1
            skipped_buckets[key] = skipped_buckets.get(key, 0) + 1
            # The ranking drops soft-deleted chores, and the count above deliberately does
            # not: it answers "how many skips", which a deleted chore's history is still part
            # of, while the ranking answers "which chore should I go and fix", which a deleted
            # chore cannot be the answer to. So the filter belongs HERE and not in
            # `done_filters` - four established metrics share that list and its comment above
            # says completed history is intentionally kept for soft-deleted chores, so a
            # predicate there would quietly re-scope all four. `Chore.deleted_at` is selected
            # purely for this branch, exactly as `Chore.repeats` is for punctuality's.
            #
            # No `repeats != manual` guard, and the reason is subtler than punctuality's. A skip
            # can only be *recorded* against a scheduled chore (skip_chore refuses an unscheduled
            # one), but `update_chore` can switch a chore to `manual` afterwards and its existing
            # skipped rows survive that - so a row here CAN belong to a chore that is unscheduled
            # today. Those are kept deliberately: the skips happened and the chore is still there
            # to be fixed, which is the whole point of the list. It is the one place this ranking
            # parts company with `punctuality.skipped`, which reads `repeats` live and drops them,
            # so the two can legitimately disagree.
            if chore_deleted_at is None:
                entry = skip_counts.setdefault(chore_id, [chore_title, household_name, 0])
                entry[2] += 1
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
                late_by = days_late(scheduled_for, completed_at, tz)
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
    # Worst-first, then by title for a stable order on ties (and by id for two chores that
    # share a title, which two households can). Sliced rather than filtered on a threshold:
    # only chores that were actually skipped have an entry at all, so "skip > 0" needs no
    # predicate, and the cap is what keeps the card a shortlist.
    #
    # `casefold()` because a raw string compare is codepoint order, which puts every capitalised
    # title ahead of every lowercase one - "Zebra duty" before "afwas" is not what the docstring
    # means by alphabetically, and chore titles are user-authored so mixed case is the norm.
    # Accented titles still sort after Z (É is U+00C9); fixing that needs real collation, which
    # is more than a cosmetic tie-break inside a five-row list is worth.
    most_skipped = sorted(
        (
            SkippedChoreStat(chore_id=cid, title=title, household_name=name, count=count)
            for cid, (title, name, count) in skip_counts.items()
        ),
        key=lambda c: (-c.count, c.title.casefold(), c.chore_id),
    )[:MOST_SKIPPED_LIMIT]

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
        most_skipped=most_skipped,
    )

from pydantic import BaseModel


class StatsKpis(BaseModel):
    """The headline numbers shown as stat tiles. `completed_in_range`, `skipped_in_range` and
    `on_time_rate` follow the selected range; `currently_overdue` and
    `active_chores` are a live snapshot (range-independent). `on_time_rate` is the
    fraction of in-range completions that were not late (on time or early), or None
    when none of them had a due date (avoids a divide-by-zero).

    Unscheduled chores count in `completed_in_range` but in none of the other three, which
    all need a due date to mean anything: `on_time_rate`'s denominator is the *scheduled*
    completions only, so it can be None even when `completed_in_range` is not.

    Skipped occurrences are counted apart, in `skipped_in_range`, and are in none of the
    others: `completed_in_range` is work done, and `on_time_rate` measures the punctuality of
    that work, so a run of skips leaves the rate untouched rather than dragging it down."""

    completed_in_range: int
    skipped_in_range: int
    currently_overdue: int
    on_time_rate: float | None
    active_chores: int


class CompletionBucket(BaseModel):
    """One point on the completions-over-time chart. `bucket` is an ISO date: the day
    itself when granularity is `day`, or the week's Monday when granularity is `week`.

    Two series over the same buckets: `count` is the work completed, `skipped` the
    occurrences closed without being done. Every bucket in the range is present with both
    at 0 if need be, so the stacked bars keep a continuous axis."""

    bucket: str
    count: int
    skipped: int


class StatusBreakdown(BaseModel):
    """The currently-open occurrences of *scheduled* chores, split by how their due date sits
    relative to today (a live snapshot). The three sum to `active_chores`, which excludes
    unscheduled chores for the same reason: they have no due date to bucket."""

    overdue: int
    today: int
    soon: int


class Punctuality(BaseModel):
    """What became of the in-range occurrences of *scheduled* chores: `late` (>0 days late),
    `on_time` (same UTC day), `early` (completed before the due day), or `skipped` (closed
    with the work not done).

    Unscheduled chores are absent, having no deadline to be measured against, so the four do
    NOT sum to `completed_in_range`. They do partition the scheduled occurrences closed in the
    range, since skipping an unscheduled chore is refused outright. Note they do not sum to
    `on_time_rate`'s denominator either, which is the first three only."""

    on_time: int
    late: int
    early: int
    skipped: int


class PersonStat(BaseModel):
    """One bar of the per-person chart: how many in-range completions this person was
    credited with, skips excluded (it ranks work done). Names only (data-minimised, like
    HouseholdMemberRead)."""

    user_id: int
    first_name: str
    last_name: str
    count: int


class SkippedChoreStat(BaseModel):
    """One bar of the most-skipped ranking: how many times this chore was skipped in the
    range. Only chores with at least one skip appear, worst-first and capped, so the list is
    the short "go and look at these" set rather than a full table.

    Soft-deleted chores are absent even though their skips still count in
    `skipped_in_range`: the ranking is a list of chores to go and fix, and a deleted one
    cannot be fixed. It is the only skip figure in this payload that drops them.

    A chore switched to unscheduled after being skipped keeps its skips here, so these counts
    can exceed `punctuality.skipped`, which reads the period live and drops such a chore.

    `title` is the chore's *current* title, not the occurrence's snapshot, so a chore
    renamed mid-range stays one row and reads the same here as on the Chores page. The
    trade-off is the mirror image of History's: there the snapshot is right because a row
    describes one past closure, here the live title is right because a row describes a chore
    that still exists and is still being skipped.

    `household_name` rides along because the page spans every household the caller is a
    deputy in, and two of them can hold a chore with the same title."""

    chore_id: int
    title: str
    household_name: str
    count: int


class StatsRead(BaseModel):
    """The aggregated Statistics payload. `range` echoes the requested window and
    `granularity` (`day`/`week`) tells the frontend how to label the time axis."""

    range: str
    granularity: str
    kpis: StatsKpis
    completions_over_time: list[CompletionBucket]
    status_breakdown: StatusBreakdown
    punctuality: Punctuality
    per_person: list[PersonStat]
    most_skipped: list[SkippedChoreStat]

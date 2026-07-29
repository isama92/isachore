from pydantic import BaseModel


class StatsKpis(BaseModel):
    """The headline numbers shown as stat tiles. `completed_in_range` and
    `on_time_rate` follow the selected range; `currently_overdue` and
    `active_chores` are a live snapshot (range-independent). `on_time_rate` is the
    fraction of in-range completions that were not late (on time or early), or None
    when none of them had a due date (avoids a divide-by-zero).

    Unscheduled chores count in `completed_in_range` but in none of the other three, which
    all need a due date to mean anything: `on_time_rate`'s denominator is the *scheduled*
    completions only, so it can be None even when `completed_in_range` is not."""

    completed_in_range: int
    currently_overdue: int
    on_time_rate: float | None
    active_chores: int


class CompletionBucket(BaseModel):
    """One point on the completions-over-time chart. `bucket` is an ISO date: the day
    itself when granularity is `day`, or the week's Monday when granularity is `week`."""

    bucket: str
    count: int


class StatusBreakdown(BaseModel):
    """The currently-open occurrences of *scheduled* chores, split by how their due date sits
    relative to today (a live snapshot). The three sum to `active_chores`, which excludes
    unscheduled chores for the same reason: they have no due date to bucket."""

    overdue: int
    today: int
    soon: int


class Punctuality(BaseModel):
    """In-range completions bucketed by lateness: `late` (>0 days late), `on_time`
    (same UTC day), `early` (completed before the due day).

    Counts only completions of scheduled chores, so the three do NOT sum to
    `completed_in_range`: an unscheduled chore has no deadline to be measured against."""

    on_time: int
    late: int
    early: int


class PersonStat(BaseModel):
    """One bar of the per-person chart: how many in-range completions this person was
    credited with. Names only (data-minimised, like HouseholdMemberRead)."""

    user_id: int
    first_name: str
    last_name: str
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

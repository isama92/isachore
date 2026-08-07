from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chore,
    ChoreOccurrence,
    Household,
    HouseholdRole,
    OccurrenceStatus,
    RepeatPeriod,
    User,
)

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeChore = Callable[..., Awaitable[Chore]]
MakeOccurrence = Callable[..., Awaitable[ChoreOccurrence]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]

# Stats are computed relative to "now", so tests anchor their fixtures to the current
# UTC day rather than a fixed reference date.
NOW = datetime.now(UTC)
TODAY_START = datetime(NOW.year, NOW.month, NOW.day, tzinfo=UTC)


def _buckets(body: dict) -> dict[str, int]:
    return {b["bucket"]: b["count"] for b in body["completions_over_time"]}


def _skipped_buckets(body: dict) -> dict[str, int]:
    return {b["bucket"]: b["skipped"] for b in body["completions_over_time"]}


async def test_stats_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/stats")
    assert resp.status_code == 401


async def test_stats_invalid_range_422(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)
    resp = await client.get("/api/v1/stats?range=year")
    assert resp.status_code == 422


async def test_stats_seeds_the_axis_for_a_caller_who_is_a_deputy_nowhere(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    """A helper-only caller gets a 200 with nothing in it ("reads narrow, writes 403"), and
    must still get a zero-seeded axis rather than an empty array.

    The day windows are per household now, so a caller whose deputy scope is empty has no zone
    to build an axis from - and `completions_over_time` is handed straight to recharts, which
    renders `[]` as blank space instead of a flat line. `local_day_bounds(now, UTC)` is the
    floor for exactly this case; it shapes only the axis, never which rows are counted.

    `test_stats_empty` does not cover it: that caller is an organiser, so their scope is
    non-empty and the axis comes from their own household's zone.
    """
    user = await make_user()
    await make_household(members=[user], roles={user.id: HouseholdRole.helper})
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats?range=7d")).json()
    assert [b["bucket"] for b in body["completions_over_time"]] != []
    assert len(body["completions_over_time"]) == 7
    assert all(b["count"] == 0 and b["skipped"] == 0 for b in body["completions_over_time"])


async def test_stats_empty(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.get("/api/v1/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"] == "30d"
    assert body["granularity"] == "day"
    assert body["kpis"] == {
        "completed_in_range": 0,
        "skipped_in_range": 0,
        "currently_overdue": 0,
        "on_time_rate": None,  # no completions -> no rate (not 0.0)
        "active_chores": 0,
    }
    assert body["status_breakdown"] == {"overdue": 0, "today": 0, "soon": 0}
    assert body["punctuality"] == {"on_time": 0, "late": 0, "early": 0, "skipped": 0}
    assert body["per_person"] == []
    # A continuous 30-day axis of zero-count buckets, both series seeded.
    assert len(body["completions_over_time"]) == 30
    assert all(b["count"] == 0 and b["skipped"] == 0 for b in body["completions_over_time"])


async def test_stats_completions_over_time_daily_buckets(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    # Two completed today, one completed three days ago (distinct scheduled_for keeps
    # the (chore_id, scheduled_for) unique guard happy; bucketing keys off completed_at).
    for offset in range(2):
        await make_occurrence(
            chore=chore,
            scheduled_for=TODAY_START - timedelta(days=offset),
            status=OccurrenceStatus.done,
            completed_by=user,
            completed_at=NOW,
        )
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START - timedelta(days=5),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=NOW - timedelta(days=3),
    )
    client = await auth_client(user)

    resp = await client.get("/api/v1/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kpis"]["completed_in_range"] == 3
    buckets = _buckets(body)
    assert buckets[NOW.date().isoformat()] == 2
    assert buckets[(NOW.date() - timedelta(days=3)).isoformat()] == 1
    assert sum(buckets.values()) == 3
    assert len(body["completions_over_time"]) == 30


async def test_stats_range_windowing_and_granularity(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=NOW,
    )
    # 40 days ago: outside 30d, inside 90d.
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START - timedelta(days=40),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=NOW - timedelta(days=40),
    )
    client = await auth_client(user)

    week = await client.get("/api/v1/stats?range=7d")
    assert week.json()["granularity"] == "day"
    assert week.json()["kpis"]["completed_in_range"] == 1

    month = await client.get("/api/v1/stats?range=30d")
    assert month.json()["granularity"] == "day"
    assert month.json()["kpis"]["completed_in_range"] == 1

    quarter = await client.get("/api/v1/stats?range=90d")
    assert quarter.json()["granularity"] == "week"
    assert quarter.json()["kpis"]["completed_in_range"] == 2
    # Weekly buckets are pre-seeded, Monday-aligned and contiguous (7-day steps),
    # spanning ~13 weeks of the 90-day window.
    days = [date.fromisoformat(b["bucket"]) for b in quarter.json()["completions_over_time"]]
    assert len(days) >= 13
    assert all(d.weekday() == 0 for d in days)
    assert all((days[i + 1] - days[i]).days == 7 for i in range(len(days) - 1))


async def test_stats_status_breakdown_and_active(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # One open occurrence per chore (the partial-unique index forbids two), so three
    # chores give one overdue, one due today, one due later this week.
    user = await make_user()
    household = await make_household(members=[user])
    for name, scheduled_for in [
        ("overdue", TODAY_START - timedelta(days=2)),
        ("today", TODAY_START),
        ("soon", TODAY_START + timedelta(days=3)),
    ]:
        chore = await make_chore(household=household, title=name, with_occurrence=False)
        await make_occurrence(
            chore=chore, scheduled_for=scheduled_for, status=OccurrenceStatus.open
        )
    client = await auth_client(user)

    resp = await client.get("/api/v1/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status_breakdown"] == {"overdue": 1, "today": 1, "soon": 1}
    assert body["kpis"]["currently_overdue"] == 1
    assert body["kpis"]["active_chores"] == 3


async def test_stats_punctuality_and_on_time_rate(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    # Late by 3 days.
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START - timedelta(days=5),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=TODAY_START - timedelta(days=2),
    )
    # On time: completed later on the due day.
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START - timedelta(days=10),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=TODAY_START - timedelta(days=10) + timedelta(hours=6),
    )
    # Early: completed the day before it was due.
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START - timedelta(days=3),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=TODAY_START - timedelta(days=4),
    )
    client = await auth_client(user)

    resp = await client.get("/api/v1/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["punctuality"] == {"on_time": 1, "late": 1, "early": 1, "skipped": 0}
    # Not-late fraction = (on_time + early) / total = 2/3.
    assert body["kpis"]["on_time_rate"] == pytest.approx(2 / 3)


async def test_stats_per_person_ranked(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com", first_name="Ava", last_name="One")
    other = await make_user(email="other@example.com", first_name="Ben", last_name="Two")
    household = await make_household(members=[me, other])
    chore = await make_chore(household=household, with_occurrence=False)
    # me completes two, other completes one.
    for offset, who in enumerate([me, me, other]):
        await make_occurrence(
            chore=chore,
            scheduled_for=TODAY_START - timedelta(days=offset),
            status=OccurrenceStatus.done,
            completed_by=who,
            completed_at=NOW,
        )
    client = await auth_client(me)

    resp = await client.get("/api/v1/stats")
    assert resp.status_code == 200
    per_person = resp.json()["per_person"]
    assert [(p["first_name"], p["count"]) for p in per_person] == [("Ava", 2), ("Ben", 1)]
    assert per_person[0]["user_id"] == me.id


async def test_stats_excludes_other_households(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com")
    stranger = await make_user(email="stranger@example.com")
    theirs = await make_household(members=[stranger], name="Theirs")
    chore = await make_chore(household=theirs, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START,
        status=OccurrenceStatus.done,
        completed_by=stranger,
        completed_at=NOW,
    )
    await make_occurrence(chore=chore, scheduled_for=NOW, status=OccurrenceStatus.open)
    # me belongs to a household of their own, empty of chores.
    await make_household(members=[me], name="Mine")
    client = await auth_client(me)

    resp = await client.get("/api/v1/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kpis"]["completed_in_range"] == 0
    assert body["kpis"]["active_chores"] == 0
    assert body["per_person"] == []


async def test_stats_filter_by_household(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    h1 = await make_household(members=[user], name="One")
    h2 = await make_household(members=[user], name="Two")
    c1 = await make_chore(household=h1, title="In one", with_occurrence=False)
    c2 = await make_chore(household=h2, title="In two", with_occurrence=False)
    for chore in (c1, c2):
        await make_occurrence(
            chore=chore,
            scheduled_for=TODAY_START,
            status=OccurrenceStatus.done,
            completed_by=user,
            completed_at=NOW,
        )
    client = await auth_client(user)

    both = await client.get("/api/v1/stats")
    assert both.json()["kpis"]["completed_in_range"] == 2
    one = await client.get(f"/api/v1/stats?household_id={h2.id}")
    assert one.json()["kpis"]["completed_in_range"] == 1


async def test_stats_filter_by_user(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com")
    other = await make_user(email="other@example.com")
    household = await make_household(members=[me, other])
    # Two completions, one each, on a chore with no open occurrence.
    done_chore = await make_chore(household=household, with_occurrence=False)
    for offset, who in enumerate([me, other]):
        await make_occurrence(
            chore=done_chore,
            scheduled_for=TODAY_START - timedelta(days=offset),
            status=OccurrenceStatus.done,
            completed_by=who,
            completed_at=NOW,
        )
    # An open chore currently on "other"'s plate.
    await make_chore(household=household, assignees=[me, other], current_assignee=other)
    client = await auth_client(me)

    mine = await client.get(f"/api/v1/stats?user_id={me.id}")
    assert mine.json()["kpis"]["completed_in_range"] == 1  # completions I'm credited with
    assert mine.json()["kpis"]["active_chores"] == 0  # nothing open is on my plate

    theirs = await client.get(f"/api/v1/stats?user_id={other.id}")
    assert theirs.json()["kpis"]["completed_in_range"] == 1
    assert theirs.json()["kpis"]["active_chores"] == 1  # the open chore assigned to them


async def test_stats_soft_deleted_chore_keeps_history_drops_from_snapshot(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START - timedelta(days=1),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=NOW,
    )
    await make_occurrence(chore=chore, scheduled_for=TODAY_START, status=OccurrenceStatus.open)
    chore.deleted_at = datetime.now(UTC)
    await db_session.commit()
    client = await auth_client(user)

    resp = await client.get("/api/v1/stats")
    assert resp.status_code == 200
    body = resp.json()
    # Completed history outlives a soft delete; the open occurrence drops from the snapshot.
    assert body["kpis"]["completed_in_range"] == 1
    assert body["kpis"]["active_chores"] == 0
    assert body["status_breakdown"] == {"overdue": 0, "today": 0, "soon": 0}


async def test_stats_null_completer_counts_in_totals_but_not_per_person(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # A completion whose completer was hard-deleted (completed_by_user_id NULL) still
    # counts in the totals/time-series/punctuality (the query outer-joins the user), but
    # is dropped from the per-person breakdown (it has no one to attribute).
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START,
        status=OccurrenceStatus.done,
        completed_by=None,
        completed_at=NOW,
    )
    client = await auth_client(user)

    resp = await client.get("/api/v1/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kpis"]["completed_in_range"] == 1
    assert body["punctuality"] == {"on_time": 1, "late": 0, "early": 0, "skipped": 0}
    assert body["per_person"] == []


# --- unscheduled chores: counted as work done, ignored where a deadline is needed ---


async def test_stats_unscheduled_is_absent_from_the_live_snapshot(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # An unscheduled chore's open occurrence has no due date to bucket, so it must not land
    # in the status donut, "overdue now" or "active chores". Its slot sits weeks in the past
    # on purpose: under a scheduled period that would read as overdue.
    user = await make_user()
    household = await make_household(members=[user])
    await make_chore(
        household=household,
        title="Unscheduled",
        start_date=NOW.date() - timedelta(days=20),
        repeats=RepeatPeriod.manual,
    )
    await make_chore(
        household=household,
        title="Scheduled",
        start_date=NOW.date() - timedelta(days=3),
        repeats=RepeatPeriod.weekly,
    )
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats")).json()
    # Only the scheduled chore counts, and the three buckets still sum to active_chores.
    assert body["kpis"]["active_chores"] == 1
    assert body["kpis"]["currently_overdue"] == 1
    assert body["status_breakdown"] == {"overdue": 1, "today": 0, "soon": 0}
    assert sum(body["status_breakdown"].values()) == body["kpis"]["active_chores"]


async def test_stats_unscheduled_completion_counts_but_is_not_punctual(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # Doing an unscheduled chore is work done: it counts in the total, the time chart and the
    # per-person ranking. It just cannot be punctual, because its slot records when the chore
    # became available rather than a deadline - read as lateness, this one would have scored
    # 10 days late and dragged the on-time rate down with it.
    user = await make_user()
    household = await make_household(members=[user])
    unscheduled = await make_chore(
        household=household, repeats=RepeatPeriod.manual, with_occurrence=False
    )
    await make_occurrence(
        chore=unscheduled,
        scheduled_for=TODAY_START - timedelta(days=10),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=NOW,
    )
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats")).json()
    assert body["kpis"]["completed_in_range"] == 1
    assert _buckets(body)[NOW.date().isoformat()] == 1
    assert [(p["user_id"], p["count"]) for p in body["per_person"]] == [(user.id, 1)]
    # Nothing punctual to report, so the rate is None rather than 0.0 or 1.0 - and
    # punctuality deliberately does NOT sum to completed_in_range.
    assert body["punctuality"] == {"on_time": 0, "late": 0, "early": 0, "skipped": 0}
    assert body["kpis"]["on_time_rate"] is None


async def test_stats_on_time_rate_ignores_unscheduled_completions(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # The rate's denominator is the scheduled completions alone. One scheduled chore done on
    # time plus one unscheduled chore done gives 1.0, not the 0.5 a total-based denominator
    # would produce.
    user = await make_user()
    household = await make_household(members=[user])
    scheduled = await make_chore(household=household, with_occurrence=False)
    unscheduled = await make_chore(
        household=household, repeats=RepeatPeriod.manual, with_occurrence=False
    )
    for chore in (scheduled, unscheduled):
        await make_occurrence(
            chore=chore,
            scheduled_for=TODAY_START,
            status=OccurrenceStatus.done,
            completed_by=user,
            completed_at=NOW,
        )
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats")).json()
    assert body["kpis"]["completed_in_range"] == 2
    assert body["punctuality"] == {"on_time": 1, "late": 0, "early": 0, "skipped": 0}
    assert body["kpis"]["on_time_rate"] == 1.0


async def test_stats_skip_is_counted_apart_from_work_done(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    """A skip closed a slot but produced nothing, so it stays out of every "work done"
    reading and is reported on its own instead."""
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=NOW,
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START - timedelta(days=1),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=NOW,
        skipped=True,
    )
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats")).json()
    today = NOW.date().isoformat()
    assert body["kpis"]["completed_in_range"] == 1
    assert body["kpis"]["skipped_in_range"] == 1
    # Two series over the same buckets, each carrying only its own kind.
    assert _buckets(body)[today] == 1
    assert _skipped_buckets(body)[today] == 1
    # The ranking is of work done, so the skip earns no bar height.
    assert [(p["user_id"], p["count"]) for p in body["per_person"]] == [(user.id, 1)]


async def test_stats_punctuality_gains_a_skipped_bucket(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    """The four buckets partition the *scheduled* occurrences closed in the range: a skip had
    a real deadline (skipping an unscheduled chore is refused outright), it just has no
    punctuality. The rate is deliberately not dragged down by it: it measures the work that
    was done, so one on-time completion beside two skips is still 100%."""
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=TODAY_START + timedelta(hours=6),
    )
    for offset in (1, 2):
        await make_occurrence(
            chore=chore,
            scheduled_for=TODAY_START - timedelta(days=offset),
            status=OccurrenceStatus.done,
            completed_by=user,
            completed_at=NOW,
            skipped=True,
        )
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats")).json()
    assert body["punctuality"] == {"on_time": 1, "late": 0, "early": 0, "skipped": 2}
    assert sum(body["punctuality"].values()) == 3  # every scheduled closure in the range
    assert body["kpis"]["on_time_rate"] == 1.0


async def test_stats_range_of_only_skips_reports_no_rate(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    """Skips are not in the rate's denominator, so a range with nothing but skips has no
    punctuality to report at all - None rather than 0.0, which would read as "always late"."""
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=NOW,
        skipped=True,
    )
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats")).json()
    assert body["kpis"]["completed_in_range"] == 0
    assert body["kpis"]["skipped_in_range"] == 1
    assert body["kpis"]["on_time_rate"] is None
    assert body["punctuality"] == {"on_time": 0, "late": 0, "early": 0, "skipped": 1}
    assert body["per_person"] == []


async def _skip_n_times(
    make_occurrence: MakeOccurrence, chore: Chore, user: User, times: int
) -> None:
    """`times` skipped closures on one chore, on consecutive days. Distinct scheduled_for
    keeps the (chore_id, scheduled_for) unique guard happy; the ranking keys off the chore."""
    for day in range(times):
        await make_occurrence(
            chore=chore,
            scheduled_for=TODAY_START - timedelta(days=day),
            status=OccurrenceStatus.done,
            completed_by=user,
            completed_at=NOW,
            skipped=True,
        )


async def test_stats_ranks_the_most_skipped_chores(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    """The ranking answers *which* chore keeps being skipped, worst first."""
    user = await make_user()
    household = await make_household(members=[user])
    for title, times in (("Bins", 3), ("Mop", 2), ("Dust", 1)):
        chore = await make_chore(household=household, title=title, with_occurrence=False)
        await _skip_n_times(make_occurrence, chore, user, times)
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats")).json()
    assert [(c["title"], c["count"]) for c in body["most_skipped"]] == [
        ("Bins", 3),
        ("Mop", 2),
        ("Dust", 1),
    ]
    # Every skip is in the KPI too, which the ranking is a breakdown of, not a subset rule.
    assert body["kpis"]["skipped_in_range"] == 6


async def test_stats_most_skipped_omits_a_chore_that_was_never_skipped(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    """ "Only chores with a skip" - a chore that was completed and never skipped has no row,
    rather than a row reading 0."""
    user = await make_user()
    household = await make_household(members=[user])
    done_only = await make_chore(household=household, title="Washing up", with_occurrence=False)
    await make_occurrence(
        chore=done_only,
        scheduled_for=TODAY_START,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=NOW,
    )
    skipped = await make_chore(household=household, title="Hoovering", with_occurrence=False)
    await _skip_n_times(make_occurrence, skipped, user, 1)
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats")).json()
    assert [c["title"] for c in body["most_skipped"]] == ["Hoovering"]
    # The completed chore is genuinely in the range, so its absence is the rule and not an
    # empty window: it is on the per-person ranking, which counts work done.
    assert body["kpis"]["completed_in_range"] == 1


async def test_stats_most_skipped_caps_the_list(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    """Six skipped chores, five rows: the card is a shortlist, so the least-skipped drops off
    rather than the list growing."""
    user = await make_user()
    household = await make_household(members=[user])
    for times in range(1, 7):
        chore = await make_chore(household=household, title=f"Chore {times}", with_occurrence=False)
        await _skip_n_times(make_occurrence, chore, user, times)
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats")).json()
    assert [(c["title"], c["count"]) for c in body["most_skipped"]] == [
        ("Chore 6", 6),
        ("Chore 5", 5),
        ("Chore 4", 4),
        ("Chore 3", 3),
        ("Chore 2", 2),
    ]
    # Dropped from the list but not from the count, so the cap cannot be mistaken for a
    # narrower window.
    assert body["kpis"]["skipped_in_range"] == 21


async def test_stats_most_skipped_breaks_ties_by_title(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    """Two chores skipped as often as each other come back alphabetically, so the card does
    not reshuffle between requests. Created in reverse order deliberately: sorted by nothing
    at all, this would come back the other way round.

    One title is lowercase on purpose. A raw string compare is codepoint order, which puts
    every capital ahead of every lowercase letter ("Z" is U+005A, "a" is U+0061), so two
    capitalised ASCII titles would pass whether or not the key casefolds - and chore titles are
    user-authored, so mixed case is the normal state of this list."""
    user = await make_user()
    household = await make_household(members=[user])
    for title in ("Zebra duty", "afwas draaien"):
        chore = await make_chore(household=household, title=title, with_occurrence=False)
        await _skip_n_times(make_occurrence, chore, user, 2)
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats")).json()
    assert [c["title"] for c in body["most_skipped"]] == ["afwas draaien", "Zebra duty"]


async def test_stats_most_skipped_keeps_a_chore_later_parked_as_unscheduled(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """Skipped three times as a weekly chore, then switched to unscheduled: still ranked.

    `skip_chore` refuses an unscheduled chore, so a skip can only be *recorded* against a
    scheduled one - but `update_chore` can switch the period afterwards and the skipped rows
    survive it. Keeping them is the point of the list: somebody reacting to being nagged about a
    chore by parking it as unscheduled is exactly who should still see it, and the chore is still
    there to be fixed. `punctuality` is the other side of that and reads `repeats` live, so this
    also pins the one place the two figures legitimately disagree.

    Worth knowing why this test has to exist. The behaviour it protects is the ABSENCE of a
    `repeats != manual` predicate, so the mutation that breaks it is an *addition* - and
    CLAUDE.md's "delete the guard and watch a test fail" rule only covers guards that are there.
    Without this case, adding the obvious-looking consistency fix to the skip branch leaves the
    whole suite green, which makes the most tempting change in this feature the untested one."""
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(
        household=household, title="Defrost the freezer", with_occurrence=False
    )
    await _skip_n_times(make_occurrence, chore, user, 3)
    # What update_chore does: the period changes and `_normalised_schedule` drops the start date.
    chore.repeats = RepeatPeriod.manual
    chore.start_date = None
    await db_session.commit()
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats")).json()
    assert [(c["title"], c["count"]) for c in body["most_skipped"]] == [("Defrost the freezer", 3)]
    # The documented divergence: punctuality reads the period live and drops the same rows, so
    # the ranking can legitimately outweigh `punctuality.skipped`.
    assert body["punctuality"]["skipped"] == 0
    assert body["kpis"]["skipped_in_range"] == 3


async def test_stats_most_skipped_uses_the_chores_current_title(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """A chore renamed mid-range is still one chore, and the ranking calls it what it is called
    now - which is what the reader sees on the Chores page they are being sent to.

    This is the mirror image of History, where the occurrence's snapshotted title is the right
    answer because a row there describes one past closure. Here a row describes a chore that
    still exists, so reading `chore_occurrences.title` would show a name nothing else in the app
    uses any more, and *which* old name would depend on row order."""
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, title="Old name", with_occurrence=False)
    await _skip_n_times(make_occurrence, chore, user, 2)
    # The skips were recorded (and their titles snapshotted) under the old name.
    chore.title = "New name"
    await db_session.commit()
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats")).json()
    assert [(c["title"], c["count"]) for c in body["most_skipped"]] == [("New name", 2)]


async def test_stats_most_skipped_drops_a_soft_deleted_chore_but_keeps_its_count(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """The ranking is a list of chores to go and fix, so a deleted one has no place on it -
    but its skips still happened, so `skipped_in_range` keeps them, exactly as completed
    history outlives a soft delete.

    Both halves matter. Without the first, a deleted chore can top the card with nothing to
    click. Without the second, the exclusion has been written into `done_filters`, which four
    other metrics share."""
    user = await make_user()
    household = await make_household(members=[user])
    live = await make_chore(household=household, title="Recycling", with_occurrence=False)
    await _skip_n_times(make_occurrence, live, user, 1)
    # More skips than the live one, so a missing filter puts it first rather than last.
    gone = await make_chore(household=household, title="Old rota", with_occurrence=False)
    await _skip_n_times(make_occurrence, gone, user, 2)
    gone.deleted_at = datetime.now(UTC)
    await db_session.commit()
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats")).json()
    assert [(c["title"], c["count"]) for c in body["most_skipped"]] == [("Recycling", 1)]
    assert body["kpis"]["skipped_in_range"] == 3


async def test_stats_most_skipped_names_each_chores_household(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    """The page spans every household the caller is a deputy in, so a row has to say where the
    chore lives - two households can hold one with the same title, and the ranking would
    otherwise show the same name twice with no way to tell them apart.

    Both are skipped equally often on purpose, so the two rows are identical on every sort key
    but the last one, `chore_id`. Be clear about what that does and does not prove: deleting
    `chore_id` from the key leaves this test GREEN, because `sorted` is stable and the rows
    happen to arrive in creation order, so what is left is unspecified rather than wrong. The
    key is there for determinism across requests - Postgres promises no row order, so without
    it the card is free to reshuffle between one poll and the next - and it matches
    `per_person`'s trailing `user_id`. Unpinnable here, like the advisory lock and the boot
    migration; equal counts at least drive the comparison rather than skipping past it."""
    user = await make_user()
    flat = await make_household(name="The Flat", members=[user])
    cabin = await make_household(name="The Cabin", members=[user])
    chores = []
    for household in (flat, cabin):
        chore = await make_chore(household=household, title="Bins", with_occurrence=False)
        await _skip_n_times(make_occurrence, chore, user, 2)
        chores.append(chore)
    assert chores[0].id < chores[1].id  # the order the assertion below rests on
    client = await auth_client(user)

    body = (await client.get("/api/v1/stats")).json()
    assert [(c["title"], c["household_name"], c["count"]) for c in body["most_skipped"]] == [
        ("Bins", "The Flat", 2),
        ("Bins", "The Cabin", 2),
    ]
    # And `household_id` narrows the ranking like every other metric, through the shared
    # closure filter. The two are indistinguishable apart from the household, so a row coming
    # back here can only be the right one.
    narrowed = (await client.get(f"/api/v1/stats?household_id={cabin.id}")).json()
    assert [(c["household_name"], c["count"]) for c in narrowed["most_skipped"]] == [
        ("The Cabin", 2)
    ]


async def test_stats_most_skipped_narrows_to_one_person(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    """`user_id` reaches the ranking through the shared closure filter, so selecting somebody
    answers "which chores does this person skip" rather than the household's whole list."""
    user = await make_user(email="me@example.com")
    other = await make_user(email="them@example.com")
    household = await make_household(members=[user, other])
    mine = await make_chore(household=household, title="Ironing", with_occurrence=False)
    await _skip_n_times(make_occurrence, mine, user, 1)
    theirs = await make_chore(household=household, title="Sweeping", with_occurrence=False)
    await _skip_n_times(make_occurrence, theirs, other, 2)
    client = await auth_client(user)

    # Unfiltered, the household's whole list, worst first.
    everyone = (await client.get("/api/v1/stats")).json()
    assert [c["title"] for c in everyone["most_skipped"]] == ["Sweeping", "Ironing"]
    # Narrowed, only the skips credited to them - and the busier chore is the OTHER person's,
    # so this cannot pass by accidentally returning the top of the unfiltered list.
    body = (await client.get(f"/api/v1/stats?user_id={user.id}")).json()
    assert [(c["title"], c["count"]) for c in body["most_skipped"]] == [("Ironing", 1)]

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chore, ChoreOccurrence, Household, OccurrenceStatus, RepeatPeriod, User

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
        "currently_overdue": 0,
        "on_time_rate": None,  # no completions -> no rate (not 0.0)
        "active_chores": 0,
    }
    assert body["status_breakdown"] == {"overdue": 0, "today": 0, "soon": 0}
    assert body["punctuality"] == {"on_time": 0, "late": 0, "early": 0}
    assert body["per_person"] == []
    # A continuous 30-day axis of zero-count buckets.
    assert len(body["completions_over_time"]) == 30
    assert all(b["count"] == 0 for b in body["completions_over_time"])


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
    assert body["punctuality"] == {"on_time": 1, "late": 1, "early": 1}
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
    assert body["punctuality"] == {"on_time": 1, "late": 0, "early": 0}
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
    assert body["punctuality"] == {"on_time": 0, "late": 0, "early": 0}
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
    assert body["punctuality"] == {"on_time": 1, "late": 0, "early": 0}
    assert body["kpis"]["on_time_rate"] == 1.0

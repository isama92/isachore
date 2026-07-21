from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.models import Chore, ChoreOccurrence, Household, OccurrenceStatus, RepeatPeriod, User

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeChore = Callable[..., Awaitable[Chore]]
MakeOccurrence = Callable[..., Awaitable[ChoreOccurrence]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


def _midnight(days_from_today: int = 0) -> datetime:
    """UTC midnight `days_from_today` days from today (the scheduled_for of an occurrence
    whose start day is that day)."""
    day = datetime.now(UTC).date() + timedelta(days=days_from_today)
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


async def test_home_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/home")
    assert resp.status_code == 401


async def test_home_lists_and_sorts_due_chores(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    for title, offset in [("Overdue", -3), ("Today", 0), ("Soon", 2), ("Far", 30)]:
        await make_chore(
            household=household,
            title=title,
            start_date=today + timedelta(days=offset),
            repeats=RepeatPeriod.manual,
        )
    client = await auth_client(user)

    resp = await client.get("/api/v1/home")
    assert resp.status_code == 200
    body = resp.json()
    # Most overdue first; there is no due-date cut-off, so the 30-days-out chore
    # is included too, sorted last.
    assert [i["title"] for i in body["items"]] == ["Overdue", "Today", "Soon", "Far"]
    assert {i["title"]: i["status"] for i in body["items"]} == {
        "Overdue": "overdue",
        "Today": "today",
        "Soon": "soon",
        # Everything in the future is "soon"; the frontend greys the dot past a week.
        "Far": "soon",
    }
    assert {i["title"]: i["days_until_due"] for i in body["items"]} == {
        "Overdue": -3,
        "Today": 0,
        "Soon": 2,
        "Far": 30,
    }


async def test_home_no_filter_shows_all_members_chores(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # With no assignee filter the view is the whole household: every member's
    # chores plus unassigned/shared ones.
    me = await make_user(email="me@example.com")
    other = await make_user(email="other@example.com")
    household = await make_household(members=[me, other])
    today = datetime.now(UTC).date()
    await make_chore(household=household, title="Unassigned", start_date=today)
    await make_chore(household=household, title="Mine", start_date=today, assignees=[me])
    await make_chore(household=household, title="Both", start_date=today, assignees=[me, other])
    await make_chore(household=household, title="Theirs", start_date=today, assignees=[other])
    client = await auth_client(me)

    resp = await client.get("/api/v1/home")
    assert {i["title"] for i in resp.json()["items"]} == {
        "Unassigned",
        "Mine",
        "Both",
        "Theirs",
    }


async def test_home_assignee_filter_keeps_mine_plus_unassigned(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # The frontend's default: seed the assignee filter with the current user, so
    # the view is their chores plus shared/unassigned ones (another member's chore
    # is excluded).
    me = await make_user(email="me@example.com")
    other = await make_user(email="other@example.com")
    household = await make_household(members=[me, other])
    today = datetime.now(UTC).date()
    await make_chore(household=household, title="Unassigned", start_date=today)
    await make_chore(household=household, title="Mine", start_date=today, assignees=[me])
    await make_chore(household=household, title="Both", start_date=today, assignees=[me, other])
    await make_chore(household=household, title="Theirs", start_date=today, assignees=[other])
    client = await auth_client(me)

    resp = await client.get("/api/v1/home", params={"assignee_id": me.id})
    assert {i["title"] for i in resp.json()["items"]} == {"Unassigned", "Mine", "Both"}


async def test_home_assignee_filter_multiple_members(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com")
    anna = await make_user(email="anna@example.com")
    bram = await make_user(email="bram@example.com")
    household = await make_household(members=[me, anna, bram])
    today = datetime.now(UTC).date()
    await make_chore(household=household, title="Unassigned", start_date=today)
    await make_chore(household=household, title="AnnaTask", start_date=today, assignees=[anna])
    await make_chore(household=household, title="BramTask", start_date=today, assignees=[bram])
    client = await auth_client(me)

    # Multiple assignee ids are OR-ed together; unassigned/shared stays visible.
    resp = await client.get(
        "/api/v1/home", params=[("assignee_id", anna.id), ("assignee_id", bram.id)]
    )
    assert {i["title"] for i in resp.json()["items"]} == {"Unassigned", "AnnaTask", "BramTask"}


async def test_home_household_filter(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    a = await make_household(name="A", members=[user])
    b = await make_household(name="B", members=[user])
    today = datetime.now(UTC).date()
    await make_chore(household=a, title="InA", start_date=today)
    await make_chore(household=b, title="InB", start_date=today)
    client = await auth_client(user)

    resp = await client.get("/api/v1/home", params={"household_id": a.id})
    assert {i["title"] for i in resp.json()["items"]} == {"InA"}
    # A household the user can't see yields an empty scope, not an error.
    foreign = await make_household(name="Foreign")
    resp = await client.get("/api/v1/home", params={"household_id": foreign.id})
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_home_items_carry_household_and_assignees(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com", first_name="Me", last_name="Myself")
    anna = await make_user(email="anna@example.com", first_name="Anna", last_name="Aardvark")
    household = await make_household(name="Home Base", members=[me, anna])
    today = datetime.now(UTC).date()
    await make_chore(household=household, title="Water plants", start_date=today, assignees=[anna])
    client = await auth_client(me)

    item = (await client.get("/api/v1/home")).json()["items"][0]
    assert item["household"] == {"id": household.id, "name": "Home Base"}
    assert item["assignees"] == [{"id": anna.id, "first_name": "Anna", "last_name": "Aardvark"}]
    # Data minimisation: the member shape must not leak email.
    assert "email" not in item["assignees"][0]


async def test_home_excludes_foreign_deleted_and_dead_household(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com")
    stranger = await make_user(email="stranger@example.com")
    my_household = await make_household(members=[me])
    other_household = await make_household(members=[stranger])
    dead_household = await make_household(members=[me], deleted_at=datetime.now(UTC))
    today = datetime.now(UTC).date()
    await make_chore(household=my_household, title="Visible", start_date=today)
    await make_chore(household=other_household, title="Foreign", start_date=today)
    await make_chore(household=dead_household, title="InDeadHousehold", start_date=today)
    deleted = await make_chore(household=my_household, title="Deleted", start_date=today)
    client = await auth_client(me)
    await client.delete(f"/api/v1/chores/{deleted.id}")

    resp = await client.get("/api/v1/home")
    assert {i["title"] for i in resp.json()["items"]} == {"Visible"}


async def test_home_progress_counts_done_and_pending(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    await make_chore(
        household=household,
        title="A",
        start_date=today - timedelta(days=1),
        repeats=RepeatPeriod.daily,
    )
    b = await make_chore(
        household=household, title="B", start_date=today, repeats=RepeatPeriod.daily
    )
    client = await auth_client(user)

    assert (await client.post(f"/api/v1/chores/{b.id}/complete")).status_code == 201

    resp = await client.get("/api/v1/home")
    # A is still overdue (pending); B was due today and is done. 1 of 2.
    assert resp.json()["progress"] == {"done_today": 1, "total_today": 2}


async def test_home_progress_excludes_early_completion(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    await make_chore(household=household, title="Pending", start_date=today - timedelta(days=2))
    future = await make_chore(
        household=household,
        title="Future",
        start_date=today + timedelta(days=3),
        repeats=RepeatPeriod.weekly,
    )
    client = await auth_client(user)
    # Completing a not-yet-due chore records a future scheduled_for, which must
    # not count toward today's progress.
    assert (await client.post(f"/api/v1/chores/{future.id}/complete")).status_code == 201

    resp = await client.get("/api/v1/home")
    assert resp.json()["progress"] == {"done_today": 0, "total_today": 1}


async def test_home_progress_ignores_completions_before_today(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    yesterday_noon = _midnight(-1) + timedelta(hours=12)
    chore = await make_chore(
        household=household,
        title="Old",
        start_date=(_midnight(-1)).date(),
        repeats=RepeatPeriod.daily,
        with_occurrence=False,
    )
    # Completed yesterday, with today's occurrence still open (pending).
    await make_occurrence(
        chore=chore,
        scheduled_for=_midnight(-1),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=yesterday_noon,
    )
    await make_occurrence(chore=chore, scheduled_for=_midnight(0), status=OccurrenceStatus.open)
    client = await auth_client(user)

    resp = await client.get("/api/v1/home")
    # Yesterday's completion is not counted today; the chore is pending today.
    assert resp.json()["progress"] == {"done_today": 0, "total_today": 1}


async def test_home_manual_one_off_disappears_after_completion(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(
        household=household, title="OneOff", start_date=today, repeats=RepeatPeriod.manual
    )
    client = await auth_client(user)

    before = await client.get("/api/v1/home")
    assert [i["title"] for i in before.json()["items"]] == ["OneOff"]

    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201

    after = await client.get("/api/v1/home")
    body = after.json()
    assert body["items"] == []  # a completed one-off never comes back
    assert body["progress"] == {"done_today": 1, "total_today": 1}


async def test_home_empty_when_user_has_no_chores(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)

    resp = await client.get("/api/v1/home")
    assert resp.status_code == 200
    assert resp.json() == {"progress": {"done_today": 0, "total_today": 0}, "items": []}


async def test_home_has_no_due_date_cutoff(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    await make_chore(household=household, title="Day7", start_date=today + timedelta(days=7))
    await make_chore(household=household, title="Day8", start_date=today + timedelta(days=8))
    await make_chore(household=household, title="Day90", start_date=today + timedelta(days=90))
    client = await auth_client(user)

    resp = await client.get("/api/v1/home")
    # There is no window any more: chores due next week and months out all show.
    assert {i["title"] for i in resp.json()["items"]} == {"Day7", "Day8", "Day90"}


async def test_home_progress_counts_completion_by_another_member(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com")
    other = await make_user(email="other@example.com")
    household = await make_household(members=[me, other])
    today = datetime.now(UTC).date()
    chore = await make_chore(
        household=household, title="Shared", start_date=today, repeats=RepeatPeriod.daily
    )
    # The other member finishes the shared (unassigned) chore today.
    client = await auth_client(other)
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201

    client = await auth_client(me)
    resp = await client.get("/api/v1/home")
    # A shared chore someone else finished today still counts toward my progress.
    assert resp.json()["progress"] == {"done_today": 1, "total_today": 1}

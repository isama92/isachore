from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.models import Chore, ChoreOccurrence, Household, OccurrenceStatus, RepeatPeriod, User

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeChore = Callable[..., Awaitable[Chore]]
MakeOccurrence = Callable[..., Awaitable[ChoreOccurrence]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


def _days_ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


async def test_unscheduled_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/unscheduled")
    assert resp.status_code == 401


async def test_unscheduled_lists_only_unscheduled_chores_alphabetically(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    for title in ["Sort the loft", "Descale the kettle"]:
        await make_chore(household=household, title=title, repeats=RepeatPeriod.manual)
    # A scheduled chore belongs to the due view, not here, however overdue it is.
    await make_chore(
        household=household,
        title="Aaa scheduled",
        start_date=datetime.now(UTC).date() - timedelta(days=10),
        repeats=RepeatPeriod.weekly,
    )
    client = await auth_client(user)

    resp = await client.get("/api/v1/unscheduled")
    assert resp.status_code == 200
    # Alphabetical, not by slot: nothing here is urgent, so "waiting longest" would be a
    # deadline in disguise. The scheduled chore would sort first if it were included.
    assert [i["title"] for i in resp.json()["items"]] == ["Descale the kettle", "Sort the loft"]


async def test_unscheduled_omits_due_state_entirely(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # The payload carries no next_due / days_until_due / status: an unscheduled chore has no
    # deadline, and shipping the fields would invite the UI to render one.
    user = await make_user()
    household = await make_household(members=[user])
    await make_chore(household=household, repeats=RepeatPeriod.manual)
    client = await auth_client(user)

    item = (await client.get("/api/v1/unscheduled")).json()["items"][0]
    assert set(item) == {
        "id",
        "title",
        "days_since_last_completion",
        "household",
        "assignees",
    }


async def test_unscheduled_reports_days_since_last_completion(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    await make_chore(household=household, title="Never", repeats=RepeatPeriod.manual)
    done = await make_chore(household=household, title="Done", repeats=RepeatPeriod.manual)
    # Two past completions: only the most recent one counts, so the older 9-day-old row
    # must not win.
    for days in (9, 4):
        await make_occurrence(
            chore=done,
            scheduled_for=_days_ago(days + 1),
            status=OccurrenceStatus.done,
            completed_by=user,
            completed_at=_days_ago(days),
        )
    client = await auth_client(user)

    body = (await client.get("/api/v1/unscheduled")).json()
    assert {i["title"]: i["days_since_last_completion"] for i in body["items"]} == {
        "Done": 4,
        "Never": None,
    }


async def test_unscheduled_treats_a_completion_with_no_timestamp_as_never_done(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # `chore_occurrences.completed_at` is nullable, so a done row without one is
    # representable even though no production path writes it. `_last_completions` drops those
    # rather than passing NULL into the day arithmetic, which would 500 the whole view.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, title="Odd", repeats=RepeatPeriod.manual)
    await make_occurrence(
        chore=chore,
        scheduled_for=_days_ago(5),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=None,
    )
    client = await auth_client(user)

    resp = await client.get("/api/v1/unscheduled")
    assert resp.status_code == 200
    assert [i["days_since_last_completion"] for i in resp.json()["items"]] == [None]


async def test_unscheduled_reports_today_as_zero(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # Completing through the endpoint is the real path to "last done today", and it also
    # proves the chore stays listed afterwards rather than disappearing like a one-off.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, title="Oven", repeats=RepeatPeriod.manual)
    client = await auth_client(user)

    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201

    items = (await client.get("/api/v1/unscheduled")).json()["items"]
    assert [(i["title"], i["days_since_last_completion"]) for i in items] == [("Oven", 0)]


async def test_unscheduled_excludes_deleted_chores(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, repeats=RepeatPeriod.manual)
    client = await auth_client(user)
    assert (await client.delete(f"/api/v1/chores/{chore.id}")).status_code == 204

    assert (await client.get("/api/v1/unscheduled")).json()["items"] == []


async def test_unscheduled_excludes_other_households(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    stranger = await make_user(email="stranger@example.com")
    mine = await make_household(name="Mine", members=[user])
    theirs = await make_household(name="Theirs", members=[stranger])
    await make_chore(household=mine, title="Mine", repeats=RepeatPeriod.manual)
    await make_chore(household=theirs, title="Theirs", repeats=RepeatPeriod.manual)
    client = await auth_client(user)

    assert [i["title"] for i in (await client.get("/api/v1/unscheduled")).json()["items"]] == [
        "Mine"
    ]


async def test_unscheduled_household_filter(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    one = await make_household(name="One", members=[user])
    two = await make_household(name="Two", members=[user])
    await make_chore(household=one, title="In one", repeats=RepeatPeriod.manual)
    await make_chore(household=two, title="In two", repeats=RepeatPeriod.manual)
    client = await auth_client(user)

    resp = await client.get(f"/api/v1/unscheduled?household_id={two.id}")
    assert [i["title"] for i in resp.json()["items"]] == ["In two"]
    # A household the user is not in yields nothing rather than a 403, like the due view.
    other = await make_household(name="Other")
    assert (await client.get(f"/api/v1/unscheduled?household_id={other.id}")).json()["items"] == []


async def test_unscheduled_assignee_filter_keeps_shared_chores(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # Filtering by member keeps that member's chores PLUS the unassigned/shared ones, which
    # belong to everybody. Same rule as the due view.
    me = await make_user(email="me@example.com")
    anna = await make_user(email="anna@example.com")
    household = await make_household(members=[me, anna])
    await make_chore(household=household, title="Mine", repeats=RepeatPeriod.manual, assignees=[me])
    await make_chore(
        household=household, title="Annas", repeats=RepeatPeriod.manual, assignees=[anna]
    )
    await make_chore(household=household, title="Shared", repeats=RepeatPeriod.manual)
    client = await auth_client(me)

    resp = await client.get(f"/api/v1/unscheduled?assignee_id={me.id}")
    assert [i["title"] for i in resp.json()["items"]] == ["Mine", "Shared"]
    # Widening to both members brings Anna's in as well.
    both = await client.get(f"/api/v1/unscheduled?assignee_id={me.id}&assignee_id={anna.id}")
    assert [i["title"] for i in both.json()["items"]] == ["Annas", "Mine", "Shared"]


async def test_unscheduled_reports_only_the_current_assignee(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # The row answers "who is on the hook", not "who could be", so it carries the open
    # occurrence's assignee alone even though the pool has two people.
    me = await make_user(email="me@example.com")
    anna = await make_user(email="anna@example.com")
    household = await make_household(members=[me, anna])
    await make_chore(
        household=household,
        title="Loft",
        repeats=RepeatPeriod.manual,
        assignees=[me, anna],
        current_assignee=anna,
    )
    client = await auth_client(me)

    item = (await client.get("/api/v1/unscheduled")).json()["items"][0]
    assert [a["id"] for a in item["assignees"]] == [anna.id]
    # Data-minimised member shape, as everywhere else: names, never emails.
    assert set(item["assignees"][0]) == {"id", "first_name", "last_name"}

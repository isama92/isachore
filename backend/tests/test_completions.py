from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AssignmentType,
    Chore,
    ChoreOccurrence,
    Household,
    HouseholdRole,
    OccurrenceStatus,
    RepeatPeriod,
    User,
    UserStatus,
)

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeChore = Callable[..., Awaitable[Chore]]
MakeOccurrence = Callable[..., Awaitable[ChoreOccurrence]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]

# A fixed reference day so date arithmetic in assertions is unambiguous.
DUE = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)


async def _slots(db_session: AsyncSession, chore_id: int) -> list[tuple[datetime, str]]:
    """The chore's occurrences as (scheduled_for, status), earliest first."""
    rows = (
        (
            await db_session.execute(
                select(ChoreOccurrence)
                .where(ChoreOccurrence.chore_id == chore_id)
                .order_by(ChoreOccurrence.scheduled_for)
            )
        )
        .scalars()
        .all()
    )
    return [(o.scheduled_for, o.status) for o in rows]


async def test_completions_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 401


async def test_completions_lists_most_recent_first(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, title="Dishes", with_occurrence=False)
    for offset, title in enumerate(["oldest", "middle", "newest"]):
        await make_occurrence(
            chore=chore,
            scheduled_for=DUE + timedelta(days=offset),
            status=OccurrenceStatus.done,
            completed_by=user,
            completed_at=DUE + timedelta(days=offset),
            title=title,
        )
    client = await auth_client(user)

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert [item["title"] for item in body["items"]] == ["newest", "middle", "oldest"]
    first = body["items"][0]
    assert first["completed_by"] == {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }
    assert first["household"] == {"id": household.id, "name": household.name}


async def test_completions_days_late_late_on_time_and_early(
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
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE + timedelta(days=3),
    )
    # On time: same date, later in the day.
    await make_occurrence(
        chore=chore,
        scheduled_for=DUE + timedelta(days=10),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE + timedelta(days=10, hours=6),
    )
    # Early: completed the day before it was due.
    await make_occurrence(
        chore=chore,
        scheduled_for=DUE + timedelta(days=20),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE + timedelta(days=19),
    )
    client = await auth_client(user)

    resp = await client.get("/api/v1/completions?sort_by=created_at&sort_dir=asc")
    assert resp.status_code == 200
    assert [item["days_late"] for item in resp.json()["items"]] == [3, 0, -1]


async def test_completions_includes_other_members(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com", first_name="Me")
    other = await make_user(email="other@example.com", first_name="Otto", last_name="Ther")
    household = await make_household(members=[me, other])
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=other,
        completed_at=DUE,
    )
    client = await auth_client(me)

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["completed_by"]["id"] == other.id


async def test_completions_excludes_other_households(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com")
    stranger = await make_user(email="stranger@example.com")
    mine = await make_household(members=[me], name="Mine")
    theirs = await make_household(members=[stranger], name="Theirs")
    my_chore = await make_chore(household=mine, title="Mine", with_occurrence=False)
    their_chore = await make_chore(household=theirs, title="Theirs", with_occurrence=False)
    await make_occurrence(
        chore=my_chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=me,
        completed_at=DUE,
    )
    await make_occurrence(
        chore=their_chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=stranger,
        completed_at=DUE,
    )
    client = await auth_client(me)

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Mine"]


async def test_completions_filter_by_household(
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
    await make_occurrence(
        chore=c1,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE,
    )
    await make_occurrence(
        chore=c2,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE,
    )
    client = await auth_client(user)

    resp = await client.get(f"/api/v1/completions?household_id={h2.id}")
    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["In two"]


async def test_completions_filter_by_user(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com")
    other = await make_user(email="other@example.com")
    household = await make_household(members=[me, other])
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=me,
        completed_at=DUE,
        title="by me",
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=DUE + timedelta(days=1),
        status=OccurrenceStatus.done,
        completed_by=other,
        completed_at=DUE + timedelta(days=1),
        title="by other",
    )
    client = await auth_client(me)

    resp = await client.get(f"/api/v1/completions?user_id={other.id}")
    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["by other"]


async def test_completions_pagination(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    for offset in range(3):
        await make_occurrence(
            chore=chore,
            scheduled_for=DUE + timedelta(days=offset),
            status=OccurrenceStatus.done,
            completed_by=user,
            completed_at=DUE + timedelta(days=offset),
        )
    client = await auth_client(user)

    page1 = (await client.get("/api/v1/completions?page=1&page_size=2")).json()
    assert page1["total"] == 3
    assert len(page1["items"]) == 2
    page2 = (await client.get("/api/v1/completions?page=2&page_size=2")).json()
    assert page2["total"] == 3
    assert len(page2["items"]) == 1


async def test_completions_includes_soft_deleted_chore(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, title="Original title", with_occurrence=False)
    # Title is snapshotted at completion; a later soft delete must not hide history.
    await make_occurrence(
        chore=chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE,
        title="Snapshot",
    )
    chore.deleted_at = datetime.now(UTC)
    await db_session.commit()
    client = await auth_client(user)

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Snapshot"]


async def test_completions_completed_by_null(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    # completed_by omitted -> completed_by_user_id is NULL (a hard-deleted user).
    await make_occurrence(
        chore=chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=None,
        completed_at=DUE,
    )
    client = await auth_client(user)

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["completed_by"] is None


async def test_completions_sort_by_title(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    # Distinct scheduled_for keeps the (chore_id, scheduled_for) unique guard happy.
    for offset, title in enumerate(["Cherry", "Apple", "Banana"]):
        await make_occurrence(
            chore=chore,
            scheduled_for=DUE + timedelta(days=offset),
            status=OccurrenceStatus.done,
            completed_by=user,
            completed_at=DUE + timedelta(days=offset),
            title=title,
        )
    client = await auth_client(user)

    resp = await client.get("/api/v1/completions?sort_by=title&sort_dir=asc")
    assert resp.status_code == 200
    assert [item["title"] for item in resp.json()["items"]] == ["Apple", "Banana", "Cherry"]


async def test_completions_excludes_soft_deleted_household(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # A completion in a since-deleted household drops out of scope, because
    # member_household_ids only returns active households.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE,
    )
    household.deleted_at = datetime.now(UTC)
    await db_session.commit()
    client = await auth_client(user)

    resp = await client.get("/api/v1/completions")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_completions_invalid_sort_422(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)
    resp = await client.get("/api/v1/completions?sort_by=nonsense")
    assert resp.status_code == 422


async def test_completion_filters_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/completions/filters")
    assert resp.status_code == 401


async def test_completion_filters_options(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com", first_name="Aaron")
    alice = await make_user(email="alice@example.com", first_name="Alice")
    bob = await make_user(email="bob@example.com", first_name="Bob")
    stranger = await make_user(email="stranger@example.com", first_name="Stranger")
    # me shares two households; alice is in both (must appear once), bob in one.
    await make_household(members=[me, alice], name="Beta")
    await make_household(members=[me, alice, bob], name="Alpha")
    # A household me is NOT in: neither it nor its member should surface.
    await make_household(members=[stranger], name="Zeta")
    client = await auth_client(me)

    resp = await client.get("/api/v1/completions/filters")
    assert resp.status_code == 200
    body = resp.json()
    assert [h["name"] for h in body["households"]] == ["Alpha", "Beta"]
    member_ids = [m["id"] for m in body["members"]]
    # Ordered by first name; alice appears once despite being in both households.
    assert [m["first_name"] for m in body["members"]] == ["Aaron", "Alice", "Bob"]
    assert stranger.id not in member_ids


async def test_completion_filters_excludes_disabled_members(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com", first_name="Aaron")
    gone = await make_user(email="gone@example.com", first_name="Gone", status=UserStatus.disabled)
    await make_household(members=[me, gone])
    client = await auth_client(me)

    resp = await client.get("/api/v1/completions/filters")
    assert resp.status_code == 200
    assert gone.id not in [m["id"] for m in resp.json()["members"]]


# --- undo (DELETE /completions/{id}) --------------------------------------


async def test_undo_latest_reopens_the_occurrence(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    t1, t2, t3 = DUE, DUE + timedelta(days=1), DUE + timedelta(days=2)
    chore = await make_chore(household=household, repeats=RepeatPeriod.daily, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=t1,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=t1,
    )
    latest = await make_occurrence(
        chore=chore,
        scheduled_for=t2,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=t2,
    )
    await make_occurrence(chore=chore, scheduled_for=t3, status=OccurrenceStatus.open)
    client = await auth_client(user)

    resp = await client.delete(f"/api/v1/completions/{latest.id}")
    assert resp.status_code == 204

    # The latest completion is reopened (due again) and its successor is gone.
    assert await _slots(db_session, chore.id) == [
        (t1, OccurrenceStatus.done),
        (t2, OccurrenceStatus.open),
    ]


async def test_undo_unscheduled_completion_reopens_the_previous_slot(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # An unscheduled chore's chain is anchored on completion timestamps rather than a grid,
    # so undoing walks it back one link: the successor opened by the second completion goes,
    # and the row that completion belonged to reopens. Done through the endpoints, because
    # the timestamps are what the undo has to order by.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, repeats=RepeatPeriod.manual, with_occurrence=True)
    client = await auth_client(user)
    for _ in range(2):
        assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201

    slots_before = await _slots(db_session, chore.id)
    assert [status for _, status in slots_before] == [
        OccurrenceStatus.done,
        OccurrenceStatus.done,
        OccurrenceStatus.open,
    ]
    entries = (await client.get("/api/v1/completions")).json()["items"]
    latest_id = max(e["id"] for e in entries)

    assert (await client.delete(f"/api/v1/completions/{latest_id}")).status_code == 204

    slots_after = await _slots(db_session, chore.id)
    # One fewer row, and the second slot is open again with its original timestamp: the
    # chore is available to do once more, crediting nobody for the undone completion.
    assert [status for _, status in slots_after] == [OccurrenceStatus.done, OccurrenceStatus.open]
    assert [slot for slot, _ in slots_after] == [slot for slot, _ in slots_before[:2]]


async def test_undo_picks_the_latest_completion_not_the_latest_slot(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # Slots only run in completion order while they come off a recurrence grid. A chore
    # switched to unscheduled while its slot was still in the future keeps that future slot
    # (see test_update_chore_weekly_to_manual...), and every later slot is a completion
    # timestamp - so the chore ends up with a done row dated LATER than the open row after
    # it. Ordering by slot would then call the wrong completion the latest: it would
    # hard-delete this genuinely-latest one and leave the chain un-rewound.
    user = await make_user()
    household = await make_household(members=[user])
    future_slot = DUE + timedelta(days=3)
    chore = await make_chore(
        household=household, repeats=RepeatPeriod.manual, with_occurrence=False
    )
    # The inherited future slot, completed first...
    await make_occurrence(
        chore=chore,
        scheduled_for=future_slot,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE,
    )
    # ...then reopened at that completion moment and completed again a day later.
    latest = await make_occurrence(
        chore=chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE + timedelta(days=1),
    )
    await make_occurrence(chore=chore, scheduled_for=DUE + timedelta(days=1))
    client = await auth_client(user)

    assert (await client.delete(f"/api/v1/completions/{latest.id}")).status_code == 204

    # The reopen branch ran: the successor is gone and `latest` is open again at its own
    # slot, with the future-slotted completion left alone as history.
    assert await _slots(db_session, chore.id) == [
        (DUE, OccurrenceStatus.open),
        (future_slot, OccurrenceStatus.done),
    ]


async def test_undo_only_completion_leaves_a_fresh_open_occurrence(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    t1, t2 = DUE, DUE + timedelta(days=1)
    chore = await make_chore(household=household, repeats=RepeatPeriod.daily, with_occurrence=False)
    only = await make_occurrence(
        chore=chore,
        scheduled_for=t1,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=t1,
    )
    await make_occurrence(chore=chore, scheduled_for=t2, status=OccurrenceStatus.open)
    client = await auth_client(user)

    resp = await client.delete(f"/api/v1/completions/{only.id}")
    assert resp.status_code == 204

    # Reopened to its original slot; the successor is gone (chore is due again).
    assert await _slots(db_session, chore.id) == [(t1, OccurrenceStatus.open)]


async def test_undo_older_completion_leaves_current_open_untouched(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    t1, t2, t3, t4 = (DUE + timedelta(days=n) for n in range(4))
    chore = await make_chore(household=household, repeats=RepeatPeriod.daily, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=t1,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=t1,
    )
    middle = await make_occurrence(
        chore=chore,
        scheduled_for=t2,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=t2,
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=t3,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=t3,
    )
    await make_occurrence(chore=chore, scheduled_for=t4, status=OccurrenceStatus.open)
    client = await auth_client(user)

    resp = await client.delete(f"/api/v1/completions/{middle.id}")
    assert resp.status_code == 204

    # Deleting a non-latest completion is a history edit: the current open occurrence
    # stands and the middle row is simply gone.
    assert await _slots(db_session, chore.id) == [
        (t1, OccurrenceStatus.done),
        (t3, OccurrenceStatus.done),
        (t4, OccurrenceStatus.open),
    ]


async def test_undo_restores_the_previous_assignee(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # A rotating chore hands off on completion; undoing that completion rolls the turn
    # back to the person who was on the hook (the stored assignee, so random survives).
    anna = await make_user(email="anna@example.com", first_name="Anna")
    bob = await make_user(email="bob@example.com", first_name="Bob")
    household = await make_household(members=[anna, bob])
    today = datetime.now(UTC).date()
    chore = await make_chore(
        household=household,
        start_date=today,
        repeats=RepeatPeriod.daily,
        assignment_type=AssignmentType.alphabetical,
        assignees=[anna, bob],
    )
    client = await auth_client(anna)

    detail = (await client.get(f"/api/v1/chores/{chore.id}")).json()
    assert detail["current_assignee"]["id"] == anna.id
    completion = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert (await client.get(f"/api/v1/chores/{chore.id}")).json()["current_assignee"][
        "id"
    ] == bob.id

    resp = await client.delete(f"/api/v1/completions/{completion.json()['id']}")
    assert resp.status_code == 204
    # Back to Anna's turn.
    assert (await client.get(f"/api/v1/chores/{chore.id}")).json()["current_assignee"][
        "id"
    ] == anna.id


async def test_undo_another_members_completion_403(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # The caller is pinned to deputy on purpose: `make_household` defaults every member to
    # organiser, and an organiser may now undo anybody's closure in their own household (see
    # test_household_roles.py for that half). Deputy is the strongest role still self-only.
    me = await make_user(email="me@example.com")
    other = await make_user(email="other@example.com")
    household = await make_household(members=[me, other], roles={me.id: HouseholdRole.deputy})
    chore = await make_chore(household=household, with_occurrence=False)
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=other,
        completed_at=DUE,
    )
    client = await auth_client(me)

    resp = await client.delete(f"/api/v1/completions/{occ.id}")
    assert resp.status_code == 403


async def test_undo_completion_in_other_household_404(
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
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=stranger,
        completed_at=DUE,
    )
    client = await auth_client(me)

    resp = await client.delete(f"/api/v1/completions/{occ.id}")
    assert resp.status_code == 404


async def test_undo_missing_completion_404(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)
    resp = await client.delete("/api/v1/completions/999999")
    assert resp.status_code == 404


async def test_undo_open_occurrence_is_not_a_completion_404(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # The auto-created open occurrence is not a completion, so it cannot be undone.
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    client = await auth_client(user)
    open_occ = (
        await db_session.execute(
            select(ChoreOccurrence).where(ChoreOccurrence.chore_id == chore.id)
        )
    ).scalar_one()

    resp = await client.delete(f"/api/v1/completions/{open_occ.id}")
    assert resp.status_code == 404


async def test_undo_requires_auth(
    client: AsyncClient,
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    occ = await make_occurrence(
        chore=chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE,
    )
    resp = await client.delete(f"/api/v1/completions/{occ.id}")
    assert resp.status_code == 401


async def test_occurrence_can_be_completed_again_after_undo(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # Full round-trip through the real endpoints: undo reopens the occurrence so it is
    # completable again.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(household=household, start_date=today, repeats=RepeatPeriod.daily)
    client = await auth_client(user)

    first = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert first.status_code == 201
    undo = await client.delete(f"/api/v1/completions/{first.json()['id']}")
    assert undo.status_code == 204
    again = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert again.status_code == 201


async def test_history_marks_skips_and_suppresses_their_lateness(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    """A skip belongs in the list (something happened to that slot) but must be readable as
    distinct from work. Its `days_late` is None like an unscheduled chore's: there was a real
    deadline, but no work to have been punctual about, and "3 days late" would read as a
    completion that ran over."""
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, with_occurrence=False)
    await make_occurrence(
        chore=chore,
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE + timedelta(days=3),
        skipped=True,
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=DUE + timedelta(days=7),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE + timedelta(days=10),
    )
    client = await auth_client(user)

    items = (await client.get("/api/v1/completions?sort_by=created_at&sort_dir=asc")).json()[
        "items"
    ]
    assert [(i["skipped"], i["days_late"]) for i in items] == [(True, None), (False, 3)]


async def test_history_outcome_filter(
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
        scheduled_for=DUE,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE,
        title="A skip",
        skipped=True,
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=DUE + timedelta(days=7),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=DUE + timedelta(days=7),
        title="Real work",
    )
    client = await auth_client(user)

    both = (await client.get("/api/v1/completions")).json()
    assert both["total"] == 2
    only_skipped = (await client.get("/api/v1/completions?outcome=skipped")).json()
    assert only_skipped["total"] == 1
    assert [i["title"] for i in only_skipped["items"]] == ["A skip"]
    only_done = (await client.get("/api/v1/completions?outcome=completed")).json()
    assert only_done["total"] == 1
    assert [i["title"] for i in only_done["items"]] == ["Real work"]


async def test_history_rejects_an_unknown_outcome(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    await make_household(members=[user])
    client = await auth_client(user)
    resp = await client.get("/api/v1/completions?outcome=maybe")
    assert resp.status_code == 422


async def test_undoing_a_skip_clears_the_flag(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """Reopening has to reset `skipped`, or the revived occurrence is completed for real later
    and still lands in history as a skip - nothing downstream re-derives it."""
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(household=household, start_date=today, repeats=RepeatPeriod.daily)
    client = await auth_client(user)

    skip = await client.post(f"/api/v1/chores/{chore.id}/skip")
    assert skip.status_code == 201
    assert (await client.delete(f"/api/v1/completions/{skip.json()['id']}")).status_code == 204

    reopened = (
        await db_session.execute(
            select(ChoreOccurrence).where(
                ChoreOccurrence.chore_id == chore.id,
                ChoreOccurrence.status == OccurrenceStatus.open,
            )
        )
    ).scalar_one()
    assert reopened.skipped is False

    # And completing it for real now records real work, not a skip.
    again = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert again.status_code == 201
    items = (await client.get("/api/v1/completions")).json()["items"]
    assert [i["skipped"] for i in items] == [False]

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
    OccurrenceStatus,
    RepeatPeriod,
    User,
)

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeChore = Callable[..., Awaitable[Chore]]
MakeOccurrence = Callable[..., Awaitable[ChoreOccurrence]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


async def test_complete_requires_auth(
    client: AsyncClient,
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    resp = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert resp.status_code == 401


async def test_complete_records_completion_and_advances(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    overdue = today - timedelta(days=2)
    chore = await make_chore(
        household=household, title="Dishes", start_date=overdue, repeats=RepeatPeriod.daily
    )
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Dishes"
    assert body["completed_by_user_id"] == user.id
    # scheduled_for is the occurrence being cleared: the overdue start date midnight.
    assert body["scheduled_for"].startswith(overdue.isoformat())
    # A single check clears the overdue chore: next occurrence is one day out.
    assert body["days_until_due"] == 1
    assert body["status"] == "soon"

    occurrences = (
        (
            await db_session.execute(
                select(ChoreOccurrence)
                .where(ChoreOccurrence.chore_id == chore.id)
                .order_by(ChoreOccurrence.scheduled_for)
            )
        )
        .scalars()
        .all()
    )
    # The cleared occurrence is now a done history row; a fresh open one is due next.
    done, upcoming = occurrences
    assert done.status == OccurrenceStatus.done
    assert done.title == "Dishes"
    assert done.completed_by_user_id == user.id
    assert upcoming.status == OccurrenceStatus.open
    assert upcoming.scheduled_for.isoformat().startswith(body["next_due"][:10])


async def test_complete_foreign_chore_404(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com")
    stranger = await make_user(email="stranger@example.com")
    other_household = await make_household(members=[stranger])
    chore = await make_chore(household=other_household)
    client = await auth_client(me)
    resp = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert resp.status_code == 404


async def test_complete_deleted_chore_404(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    client = await auth_client(user)
    await client.delete(f"/api/v1/chores/{chore.id}")
    resp = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert resp.status_code == 404


async def test_complete_manual_one_off_twice_conflicts(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(household=household, start_date=today, repeats=RepeatPeriod.manual)
    client = await auth_client(user)

    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    # A one-off has no next occurrence, so a second completion is a conflict.
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 409


async def test_complete_duplicate_occurrence_conflicts(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    # Simulates a concurrent double-submit: an occurrence already exists at the slot the
    # completion is about to materialise as the successor (same chore_id +
    # scheduled_for), so the unique guard yields a 409 rather than a 500.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(household=household, start_date=today, repeats=RepeatPeriod.daily)
    tomorrow = datetime(today.year, today.month, today.day, tzinfo=UTC) + timedelta(days=1)
    # A row already sits on tomorrow's slot (the successor the endpoint will insert).
    await make_occurrence(
        chore=chore,
        scheduled_for=tomorrow,
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=tomorrow,
    )
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert resp.status_code == 409


async def test_complete_another_members_chore_allowed(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    me = await make_user(email="me@example.com")
    other = await make_user(email="other@example.com")
    household = await make_household(members=[me, other])
    today = datetime.now(UTC).date()
    # Assigned to `other`, but any household member may check it off.
    chore = await make_chore(
        household=household, start_date=today, repeats=RepeatPeriod.manual, assignees=[other]
    )
    client = await auth_client(me)

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert resp.status_code == 201
    assert resp.json()["completed_by_user_id"] == me.id


async def test_complete_credits_named_assignee(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # I complete a chore assigned to Anna and credit the completion to her, so the
    # History shows it under her name. The chore's assignees are unchanged.
    me = await make_user(email="me@example.com")
    anna = await make_user(email="anna@example.com")
    household = await make_household(members=[me, anna])
    today = datetime.now(UTC).date()
    chore = await make_chore(
        household=household, start_date=today, repeats=RepeatPeriod.manual, assignees=[anna]
    )
    client = await auth_client(me)

    resp = await client.post(
        f"/api/v1/chores/{chore.id}/complete", json={"completed_by_user_id": anna.id}
    )
    assert resp.status_code == 201
    assert resp.json()["completed_by_user_id"] == anna.id
    # The assignees were not touched by crediting the completion.
    detail = (await client.get(f"/api/v1/chores/{chore.id}")).json()
    assert [a["id"] for a in detail["assignees"]] == [anna.id]


async def test_complete_credit_to_self_always_allowed(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # Crediting yourself is fine even when you are not an assignee (e.g. an
    # unassigned chore, or the "Done as me" branch on someone else's chore).
    me = await make_user(email="me@example.com")
    anna = await make_user(email="anna@example.com")
    household = await make_household(members=[me, anna])
    today = datetime.now(UTC).date()
    chore = await make_chore(
        household=household, start_date=today, repeats=RepeatPeriod.manual, assignees=[anna]
    )
    client = await auth_client(me)

    resp = await client.post(
        f"/api/v1/chores/{chore.id}/complete", json={"completed_by_user_id": me.id}
    )
    assert resp.status_code == 201
    assert resp.json()["completed_by_user_id"] == me.id


async def test_complete_credit_to_non_assignee_rejected(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # A completion can only be credited to the current user or one of the chore's
    # assignees, never to an arbitrary member.
    me = await make_user(email="me@example.com")
    anna = await make_user(email="anna@example.com")
    bram = await make_user(email="bram@example.com")
    household = await make_household(members=[me, anna, bram])
    today = datetime.now(UTC).date()
    chore = await make_chore(
        household=household, start_date=today, repeats=RepeatPeriod.manual, assignees=[anna]
    )
    client = await auth_client(me)

    resp = await client.post(
        f"/api/v1/chores/{chore.id}/complete", json={"completed_by_user_id": bram.id}
    )
    assert resp.status_code == 400


async def test_repeated_completion_marches_the_due_date_forward(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # Regression for the schedule-anchoring bug: completing a daily chore several
    # times in a row (same day) must advance the due date by one calendar day each
    # time (in 1 day, then 2, then 3), not stay stuck at "due tomorrow" because the
    # schedule was re-anchored to the wall-clock completion time.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(household=household, start_date=today, repeats=RepeatPeriod.daily)
    client = await auth_client(user)

    scheduled_fors = []
    for expected_days in (1, 2, 3):
        resp = await client.post(f"/api/v1/chores/{chore.id}/complete")
        assert resp.status_code == 201
        body = resp.json()
        assert body["days_until_due"] == expected_days
        scheduled_fors.append(body["scheduled_for"])

    # Each completion cleared the next occurrence, one calendar day later than the last.
    assert scheduled_fors[0] < scheduled_fors[1] < scheduled_fors[2]


# --- rotation (who is on the hook after a completion) ----------------------


async def _daily_rotating_chore(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    *,
    assignment_type: AssignmentType,
    turn_length: int = 1,
    current_assignee_first: bool = False,
) -> tuple[Chore, User, User]:
    anna = await make_user(email="anna@example.com", first_name="Anna")
    bob = await make_user(email="bob@example.com", first_name="Bob")
    household = await make_household(members=[anna, bob])
    today = datetime.now(UTC).date()
    chore = await make_chore(
        household=household,
        start_date=today,
        repeats=RepeatPeriod.daily,
        assignment_type=assignment_type,
        turn_length=turn_length,
        assignees=[anna, bob],
        current_assignee=anna if current_assignee_first else None,
    )
    return chore, anna, bob


async def _current_assignee_id(client: AsyncClient, chore_id: int) -> int | None:
    body = (await client.get(f"/api/v1/chores/{chore_id}")).json()
    return body["current_assignee"]["id"] if body["current_assignee"] else None


async def test_complete_alphabetical_hands_off_each_completion(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    chore, anna, bob = await _daily_rotating_chore(
        make_user, make_household, make_chore, assignment_type=AssignmentType.alphabetical
    )
    client = await auth_client(anna)

    assert await _current_assignee_id(client, chore.id) == anna.id  # alphabetical initial
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    assert await _current_assignee_id(client, chore.id) == bob.id
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    assert await _current_assignee_id(client, chore.id) == anna.id  # wraps back


async def test_complete_take_turns_holds_then_hands_off(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # turn_length 3: Anna holds the chore for three completions, then it hands to Bob.
    chore, anna, bob = await _daily_rotating_chore(
        make_user,
        make_household,
        make_chore,
        assignment_type=AssignmentType.alphabetical,
        turn_length=3,
    )
    client = await auth_client(anna)

    assert await _current_assignee_id(client, chore.id) == anna.id
    for _ in range(2):
        assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
        assert await _current_assignee_id(client, chore.id) == anna.id  # still her turn
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    assert await _current_assignee_id(client, chore.id) == bob.id  # third completion hands off


async def test_complete_manual_never_rotates(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    chore, anna, _bob = await _daily_rotating_chore(
        make_user,
        make_household,
        make_chore,
        assignment_type=AssignmentType.manual,
        current_assignee_first=True,
    )
    client = await auth_client(anna)

    assert await _current_assignee_id(client, chore.id) == anna.id
    for _ in range(2):
        assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
        assert await _current_assignee_id(client, chore.id) == anna.id  # manual stays put


async def test_complete_least_done_gives_it_to_whoever_did_least(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # Crediting each completion to the current assignee (as the Home dialog does) makes
    # least_done alternate: the person just credited is no longer the least-done one.
    chore, anna, bob = await _daily_rotating_chore(
        make_user, make_household, make_chore, assignment_type=AssignmentType.least_done
    )
    client = await auth_client(anna)

    async def complete_as(assignee_id: int) -> None:
        resp = await client.post(
            f"/api/v1/chores/{chore.id}/complete", json={"completed_by_user_id": assignee_id}
        )
        assert resp.status_code == 201

    assert await _current_assignee_id(client, chore.id) == anna.id  # tie -> alphabetical
    await complete_as(anna.id)
    assert await _current_assignee_id(client, chore.id) == bob.id  # Anna now ahead
    await complete_as(bob.id)
    assert await _current_assignee_id(client, chore.id) == anna.id  # level -> alphabetical

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
)

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeChore = Callable[..., Awaitable[Chore]]
MakeOccurrence = Callable[..., Awaitable[ChoreOccurrence]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]

NOW = datetime.now(UTC)
TODAY_START = datetime(NOW.year, NOW.month, NOW.day, tzinfo=UTC)


async def _occurrences(session: AsyncSession, chore_id: int) -> list[ChoreOccurrence]:
    return list(
        (
            await session.execute(
                select(ChoreOccurrence)
                .where(ChoreOccurrence.chore_id == chore_id)
                .order_by(ChoreOccurrence.scheduled_for)
            )
        )
        .scalars()
        .all()
    )


async def _open_assignee(session: AsyncSession, chore_id: int) -> int | None:
    occ = (
        await session.execute(
            select(ChoreOccurrence).where(
                ChoreOccurrence.chore_id == chore_id,
                ChoreOccurrence.status == OccurrenceStatus.open,
            )
        )
    ).scalar_one()
    return occ.assignee_id


async def test_skip_requires_auth(
    client: AsyncClient,
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    resp = await client.post(f"/api/v1/chores/{chore.id}/skip")
    assert resp.status_code == 401


async def test_skip_closes_the_occurrence_and_advances(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    overdue = NOW.date() - timedelta(days=2)
    chore = await make_chore(
        household=household, title="Dishes", start_date=overdue, repeats=RepeatPeriod.daily
    )
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/skip")
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Dishes"
    assert body["completed_by_user_id"] == user.id
    assert body["scheduled_for"].startswith(overdue.isoformat())
    # The chore moves on exactly as completing it would: skip-missed applied, one day out.
    assert body["days_until_due"] == 1
    assert body["status"] == "soon"

    occurrences = await _occurrences(db_session, chore.id)
    assert len(occurrences) == 2
    closed, successor = occurrences
    assert closed.status == OccurrenceStatus.done
    assert closed.skipped is True
    assert closed.completed_by_user_id == user.id
    assert closed.completed_at is not None
    assert closed.title == "Dishes"  # snapshotted like any other closure
    assert successor.status == OccurrenceStatus.open
    assert successor.skipped is False


async def test_skip_refuses_an_unscheduled_chore(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """An unscheduled chore is never due, so there is no deadline to move past. Refusing it
    here is what keeps every skipped row attached to a scheduled chore, which the punctuality
    breakdown in stats relies on."""
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, repeats=RepeatPeriod.manual)
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/skip")
    assert resp.status_code == 400
    assert "never due" in resp.json()["detail"]
    # And it really is untouched: still one open occurrence, nothing closed.
    occurrences = await _occurrences(db_session, chore.id)
    assert [o.status for o in occurrences] == [OccurrenceStatus.open]


async def test_skip_409_when_nothing_is_open(
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
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/skip")
    assert resp.status_code == 409


async def test_skip_404_for_a_chore_outside_the_users_households(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    outsider = await make_user(email="outsider@example.com")
    await make_household(members=[outsider], name="Theirs")
    owner = await make_user(email="owner@example.com")
    household = await make_household(members=[owner], name="Ours")
    chore = await make_chore(household=household)
    client = await auth_client(outsider)

    resp = await client.post(f"/api/v1/chores/{chore.id}/skip")
    assert resp.status_code == 404


async def test_a_helper_may_skip(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    """Ungated like completing: deciding not to do a chore is part of doing the chores, so
    the weakest role reaches it."""
    helper = await make_user()
    household = await make_household(members=[helper], roles={helper.id: HouseholdRole.helper})
    chore = await make_chore(household=household)
    client = await auth_client(helper)

    resp = await client.post(f"/api/v1/chores/{chore.id}/skip")
    assert resp.status_code == 201


async def test_skip_keeps_the_turn_while_completing_hands_it_on(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """The rule that makes skipping honest: it does not move work onto a housemate.

    Both halves matter. The second one (completing rotates to Ben) is what makes the first
    one mean something: without it, "still Ava" could just be a chore that never rotates.
    """
    ava = await make_user(email="ava@example.com", first_name="Ava")
    ben = await make_user(email="ben@example.com", first_name="Ben")
    household = await make_household(members=[ava, ben])
    chore = await make_chore(
        household=household,
        start_date=NOW.date(),
        repeats=RepeatPeriod.daily,
        assignment_type=AssignmentType.alphabetical,
        assignees=[ava, ben],
    )
    assert await _open_assignee(db_session, chore.id) == ava.id
    client = await auth_client(ava)

    assert (await client.post(f"/api/v1/chores/{chore.id}/skip")).status_code == 201
    assert await _open_assignee(db_session, chore.id) == ava.id

    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    assert await _open_assignee(db_session, chore.id) == ben.id


async def test_skip_does_not_consume_a_turn(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """With `turn_length=2` the handoff lands on the second *completion*, and a skip in
    between must not bring it forward: it produced no work, so it spends none of the turn."""
    ava = await make_user(email="ava@example.com", first_name="Ava")
    ben = await make_user(email="ben@example.com", first_name="Ben")
    household = await make_household(members=[ava, ben])
    chore = await make_chore(
        household=household,
        start_date=NOW.date() - timedelta(days=3),
        repeats=RepeatPeriod.daily,
        assignment_type=AssignmentType.alphabetical,
        turn_length=2,
        assignees=[ava, ben],
    )
    client = await auth_client(ava)

    # Completion 1 of Ava's two-completion turn.
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    assert await _open_assignee(db_session, chore.id) == ava.id
    # A skip mid-turn. If skips counted, this would be "completion 2" and hand over to Ben.
    assert (await client.post(f"/api/v1/chores/{chore.id}/skip")).status_code == 201
    assert await _open_assignee(db_session, chore.id) == ava.id
    # Completion 2: now the turn really is up.
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    assert await _open_assignee(db_session, chore.id) == ben.id


async def test_skip_earns_no_least_done_credit(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """`least_done` ranks on work done, so a skip must not pad anyone's tally - otherwise
    skipping is the cheap way to look busy and stop being picked.

    The counts are set up so the skip is the deciding one. Ava holds one real completion and
    one skip, Ben none; when Ben completes, the honest tally is 1-1, which ties and falls to
    Ava alphabetically. Counting the skip would make it Ava 2, Ben 1, and send it back to Ben.
    """
    ava = await make_user(email="ava@example.com", first_name="Ava")
    ben = await make_user(email="ben@example.com", first_name="Ben")
    household = await make_household(members=[ava, ben])
    chore = await make_chore(
        household=household,
        repeats=RepeatPeriod.daily,
        assignment_type=AssignmentType.least_done,
        assignees=[ava, ben],
        with_occurrence=False,
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START - timedelta(days=10),
        status=OccurrenceStatus.done,
        completed_by=ava,
        completed_at=NOW - timedelta(days=10),
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=TODAY_START - timedelta(days=9),
        status=OccurrenceStatus.done,
        completed_by=ava,
        completed_at=NOW - timedelta(days=9),
        skipped=True,
    )
    await make_occurrence(
        chore=chore, scheduled_for=TODAY_START, status=OccurrenceStatus.open, assignee=ben
    )
    client = await auth_client(ben)

    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    assert await _open_assignee(db_session, chore.id) == ava.id


async def test_skipping_a_poolless_chore_leaves_it_unassigned(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """No pool at all, so there is nobody the successor could go to."""
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, start_date=NOW.date(), assignees=[])
    client = await auth_client(user)

    assert (await client.post(f"/api/v1/chores/{chore.id}/skip")).status_code == 201
    assert await _open_assignee(db_session, chore.id) is None


async def test_skipping_a_chore_handed_back_to_the_household_keeps_it_that_way(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """NULL is "nobody's turn", not "no opinion", so a skip must not invent a turn out of it.

    The pool here is deliberately NON-empty and the strategy one that would happily name
    somebody: with an empty pool the successor comes back unassigned whatever the rule says,
    so such a test would assert a fall-through and pin nothing (see the poolless case above).
    Here `alphabetical` would hand it to Ava if the unassigned branch were dropped.
    """
    ava = await make_user(email="ava@example.com", first_name="Ava")
    ben = await make_user(email="ben@example.com", first_name="Ben")
    household = await make_household(members=[ava, ben])
    chore = await make_chore(
        household=household,
        repeats=RepeatPeriod.daily,
        assignment_type=AssignmentType.alphabetical,
        assignees=[ava, ben],
        with_occurrence=False,
    )
    # The state ChoreEdit's `clear_current_assignee` leaves behind: open, pool intact, nobody up.
    await make_occurrence(chore=chore, scheduled_for=TODAY_START, status=OccurrenceStatus.open)
    client = await auth_client(ava)

    assert (await client.post(f"/api/v1/chores/{chore.id}/skip")).status_code == 201
    assert await _open_assignee(db_session, chore.id) is None


async def test_skipping_re_derives_when_the_assignee_left_the_pool(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """The other half of the rule: keeping the turn is impossible when the row names somebody
    the pool no longer holds, and leaving it there parks the chore on a person who cannot do
    it. Only then does the strategy get to pick."""
    ava = await make_user(email="ava@example.com", first_name="Ava")
    ben = await make_user(email="ben@example.com", first_name="Ben")
    cara = await make_user(email="cara@example.com", first_name="Cara")
    household = await make_household(members=[ava, ben, cara])
    chore = await make_chore(
        household=household,
        repeats=RepeatPeriod.daily,
        assignment_type=AssignmentType.alphabetical,
        assignees=[ava, ben],
        with_occurrence=False,
    )
    # Cara holds the occurrence but is not in the chore's pool (dropped by a later edit).
    await make_occurrence(
        chore=chore, scheduled_for=TODAY_START, status=OccurrenceStatus.open, assignee=cara
    )
    client = await auth_client(ava)

    assert (await client.post(f"/api/v1/chores/{chore.id}/skip")).status_code == 201
    assert await _open_assignee(db_session, chore.id) == ava.id

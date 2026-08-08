from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
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


async def test_complete_unscheduled_is_repeatable(
    db_session: AsyncSession,
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # An unscheduled chore is done on demand, over and over: each completion reopens it, so
    # three clicks record three completions and leave the chore still open.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(household=household, start_date=today, repeats=RepeatPeriod.manual)
    client = await auth_client(user)

    for _ in range(3):
        assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201

    rows = (
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
    assert [r.status for r in rows] == [
        OccurrenceStatus.done,
        OccurrenceStatus.done,
        OccurrenceStatus.done,
        OccurrenceStatus.open,
    ]
    # Each successor is anchored at the completion moment of the row before it, which is
    # both what "available again since" means here and what keeps the slots distinct under
    # uq_occurrence_chore_scheduled when a chore is done twice in one day.
    done = [r for r in rows if r.status == OccurrenceStatus.done]
    assert [r.scheduled_for for r in rows[1:]] == [r.completed_at for r in done]


async def test_complete_unscheduled_reports_no_deadline_in_history(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # The slot of an unscheduled chore records availability, not a deadline, so History
    # must not read the gap since it opened as lateness.
    user = await make_user()
    household = await make_household(members=[user])
    long_ago = datetime.now(UTC).date() - timedelta(days=40)
    chore = await make_chore(household=household, start_date=long_ago, repeats=RepeatPeriod.manual)
    client = await auth_client(user)

    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201

    entries = (await client.get("/api/v1/completions")).json()["items"]
    assert [e["days_late"] for e in entries] == [None]


async def test_complete_walks_the_successor_past_a_slot_already_completed(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    db_session: AsyncSession,
    auth_client: AuthClient,
) -> None:
    # A done row already sits on the slot the completion is about to materialise as the
    # successor. `free_slot_from` walks past it, so the chore lands on the next free slot
    # instead of colliding on uq_occurrence_chore_scheduled.
    #
    # This used to assert a 409, described as a concurrent double-submit - but it is not one:
    # a real double-submit races to insert an *open* row, and there can only ever be one of
    # those per chore. What it actually built was a chore whose open slot sits behind its own
    # history, which the unscheduled -> scheduled round trip reaches for real, and the 409 it
    # got was unclearable because retrying recomputed the same occupied slot. The genuine
    # concurrent race still maps to a 409 through the IntegrityError catch; that path is not
    # reachable under fixtures giving each test one connection.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(household=household, start_date=today, repeats=RepeatPeriod.daily)
    midnight = datetime(today.year, today.month, today.day, tzinfo=UTC)
    await make_occurrence(
        chore=chore,
        scheduled_for=midnight + timedelta(days=1),
        status=OccurrenceStatus.done,
        completed_by=user,
        completed_at=midnight + timedelta(days=1),
    )
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert resp.status_code == 201
    assert resp.json()["next_due"][:10] == (midnight + timedelta(days=2)).date().isoformat()
    upcoming = await db_session.scalar(
        select(ChoreOccurrence).where(
            ChoreOccurrence.chore_id == chore.id,
            ChoreOccurrence.status == OccurrenceStatus.open,
        )
    )
    assert upcoming is not None
    assert upcoming.scheduled_for == midnight + timedelta(days=2)


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
    # Level again, and Bob is the one up. He is dropped from the tie, which leaves Anna - the
    # same answer the old plain `min` gave, since Bob sorted second and it was already
    # skipping him. That is exactly why this test never caught #58; the one below does.
    assert await _current_assignee_id(client, chore.id) == anna.id


async def test_complete_least_done_hands_over_the_moment_the_pair_are_level(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    """Issue #58 end to end: the tie has to fall with the ALPHABETICALLY FIRST member on the
    hook. That is the household's report - one person a completion ahead, the other levels up,
    and the chore stayed put instead of moving across."""
    chore, anna, bob = await _daily_rotating_chore(
        make_user, make_household, make_chore, assignment_type=AssignmentType.least_done
    )
    client = await auth_client(anna)

    async def complete_as(assignee_id: int) -> None:
        resp = await client.post(
            f"/api/v1/chores/{chore.id}/complete", json={"completed_by_user_id": assignee_id}
        )
        assert resp.status_code == 201

    assert await _current_assignee_id(client, chore.id) == anna.id
    # Bob one ahead, Anna on zero: she is the strict minimum, so she keeps it while she
    # catches up. This half fails if the fix over-reaches into excluding whoever is up.
    await complete_as(bob.id)
    assert await _current_assignee_id(client, chore.id) == anna.id
    # One each now, with Anna still on the hook. This is the assertion that used to fail: a
    # tie handed the chore straight back to her because she sorts first.
    await complete_as(anna.id)
    assert await _current_assignee_id(client, chore.id) == bob.id


async def test_complete_least_done_ranks_on_the_counts_with_nobody_on_the_hook(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    """An unassigned chore ("nobody in particular") re-derives from scratch at every turn
    boundary, because there is no current assignee to hand over from. That fallback used to
    drop the tally on the floor and answer alphabetically, so the person who had done all the
    work kept being handed it back."""
    now = datetime.now(UTC)
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    anna = await make_user(email="anna@example.com", first_name="Anna")
    bob = await make_user(email="bob@example.com", first_name="Bob")
    household = await make_household(members=[anna, bob])
    chore = await make_chore(
        household=household,
        start_date=today_start.date() - timedelta(days=1),
        repeats=RepeatPeriod.daily,
        assignment_type=AssignmentType.least_done,
        assignees=[anna, bob],
        with_occurrence=False,
    )
    # Anna has done it once; the open row is the state `clear_current_assignee` leaves behind.
    # Done row first, open row last - see `make_occurrence` on why the chain order matters.
    await make_occurrence(
        chore=chore,
        scheduled_for=today_start - timedelta(days=1),
        status=OccurrenceStatus.done,
        completed_by=anna,
        completed_at=today_start - timedelta(hours=16),
    )
    await make_occurrence(chore=chore, scheduled_for=today_start, status=OccurrenceStatus.open)
    client = await auth_client(anna)

    resp = await client.post(
        f"/api/v1/chores/{chore.id}/complete", json={"completed_by_user_id": anna.id}
    )
    assert resp.status_code == 201
    # Anna is now two ahead of Bob, so the chore has to land on Bob. Alphabetically it would
    # be Anna, which is what made this worth pinning: nothing else exercises that fallback.
    assert await _current_assignee_id(client, chore.id) == bob.id


# --- recurrence interval and pinned weekdays -------------------------------
#
# These endpoint tests must hold whatever weekday the suite runs on, and there is no
# freezegun/time-machine here, so the weekday sets are derived from today rather than
# hardcoded. Picking today's weekday plus the one three days later makes the strides
# deterministically 3 then 4 for every possible "today": when the +3 day falls later in
# the same week it is a plain intra-week hop, and when it wraps, the week-crossing
# formula (7 - weekday + earliest) yields the same 3. The exact date arithmetic is pinned
# in test_chores_core.py, which is free of `now()`.


async def test_complete_twice_a_week_alternates_between_the_two_days(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # "We start the washing machine on Tuesday and on Friday": two slots a week, so the
    # stride alternates 3 and 4 days instead of being a flat 7.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(
        household=household,
        start_date=today,
        repeats=RepeatPeriod.weekly,
        weekdays=[today.weekday(), (today.weekday() + 3) % 7],
    )
    client = await auth_client(user)

    first = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert first.status_code == 201
    assert first.json()["days_until_due"] == 3  # the second day of the week

    second = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert second.status_code == 201
    # A stride of 4 from a slot already 3 days out, so 7 days from today: back round to
    # the first of the two days. Two completions are needed to see this at all.
    assert second.json()["days_until_due"] == 7


async def test_complete_pinned_weekday_overdue_skips_the_backlog(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    # "We take out the garbage on Tuesday", three weeks neglected: one completion clears
    # it and it lands on the same weekday next week, with nothing backfilled.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(
        household=household,
        start_date=today - timedelta(days=21),
        repeats=RepeatPeriod.weekly,
        weekdays=[today.weekday()],
    )
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert resp.status_code == 201
    assert resp.json()["days_until_due"] == 7

    rows = (
        (
            await db_session.execute(
                select(ChoreOccurrence).where(ChoreOccurrence.chore_id == chore.id)
            )
        )
        .scalars()
        .all()
    )
    # Exactly one done row and one open row: the three missed Tuesdays are not backfilled.
    assert len(rows) == 2
    assert sorted(row.status for row in rows) == [OccurrenceStatus.done, OccurrenceStatus.open]


async def test_complete_every_two_days_marches_by_the_interval(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # "We run the dishwasher every 2 days": the interval-aware version of the
    # march-the-due-date-forward regression test.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(
        household=household, start_date=today, repeats=RepeatPeriod.daily, repeat_interval=2
    )
    client = await auth_client(user)

    for expected in (2, 4, 6):
        resp = await client.post(f"/api/v1/chores/{chore.id}/complete")
        assert resp.status_code == 201
        assert resp.json()["days_until_due"] == expected


async def test_complete_fortnightly_pinned_weekday_spends_the_interval(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # A single weekday every other week: the week crossing spends the interval, so the
    # next slot is two weeks out rather than one. Proves the interval and the weekday
    # pinning reach the recurrence helpers together, not just one or the other.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(
        household=household,
        start_date=today,
        repeats=RepeatPeriod.weekly,
        repeat_interval=2,
        weekdays=[today.weekday()],
    )
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert resp.status_code == 201
    assert resp.json()["days_until_due"] == 14


async def test_complete_unscheduled_created_with_a_schedule_ignores_it(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    # Created through the API, so this proves the schema's normalisation reached the DB
    # rather than being cosmetic in the response: an unscheduled chore keeps no schedule at
    # all, whatever the payload carried, and reopens on each completion rather than stepping
    # the interval and weekdays it was sent.
    user = await make_user()
    household = await make_household(members=[user])
    client = await auth_client(user)

    created = await client.post(
        "/api/v1/chores",
        json={
            "household_id": household.id,
            "title": "Fix the shelf",
            "start_date": datetime.now(UTC).date().isoformat(),
            "repeats": "manual",
            "assignment_type": "manual",
            "repeat_interval": 4,
            "weekdays": [1, 4],
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["weekdays"] is None
    assert body["repeat_interval"] == 1
    assert body["start_date"] is None

    chore_id = body["id"]
    # Reopens at the completion moment, so it reads as due today rather than four weeks on.
    first = await client.post(f"/api/v1/chores/{chore_id}/complete")
    assert first.status_code == 201
    assert first.json()["days_until_due"] == 0
    assert (await client.post(f"/api/v1/chores/{chore_id}/complete")).status_code == 201


# --- recording a completion on its due day ----------------------------------
#
# `backdate` answers "when was it done" rather than "when was it ticked": the closure is dated
# at the end of the occurrence's own local day, so it reads as on time AND `advance_anchor`
# stops rolling past the occurrences that were missed. The zone-sensitive half lives in
# test_timezones.py; everything here is structural and reads the same in UTC.
#
# The clock is pinned throughout, since "which day was it due" and "which day is it now" are
# the entire subject. Same seam and same reasoning as test_timezones.py's twin, kept local
# because moving that one would churn a file this change has no other business in.

DUE_DAY = date(2026, 8, 6)
DUE_SLOT = datetime(2026, 8, 6, tzinfo=UTC)
NOW = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)  # two days after DUE_DAY
END_OF_DUE_DAY = datetime(2026, 8, 6, 23, 59, 59, 999999, tzinfo=UTC)


def pin_clock(monkeypatch: pytest.MonkeyPatch, moment: datetime = NOW) -> None:
    monkeypatch.setattr(clock, "now", lambda: moment)


async def open_slot(session: AsyncSession, chore: Chore) -> datetime:
    slot = await session.scalar(
        select(ChoreOccurrence.scheduled_for).where(
            ChoreOccurrence.chore_id == chore.id,
            ChoreOccurrence.status == OccurrenceStatus.open,
        )
    )
    assert slot is not None
    return slot


async def closure(session: AsyncSession, completion_id: int) -> ChoreOccurrence:
    row = await session.scalar(select(ChoreOccurrence).where(ChoreOccurrence.id == completion_id))
    assert row is not None
    return row


async def test_complete_backdated_records_the_end_of_the_due_day_and_advances_one_interval(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, start_date=DUE_DAY, repeats=RepeatPeriod.daily)
    pin_clock(monkeypatch)
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete", json={"backdate": True})

    assert resp.status_code == 201
    body = resp.json()
    assert (await closure(db_session, body["id"])).completed_at == END_OF_DUE_DAY
    # The successor is one interval on from the slot, NOT from today: 7 August, which is still
    # a day overdue. That is the whole point - the missed day is offered rather than swallowed.
    assert await open_slot(db_session, chore) == DUE_SLOT + timedelta(days=1)
    assert body["days_until_due"] == -1
    assert body["status"] == "overdue"
    # `created_at` on a closure means the completion timestamp (COMPLETION_SORT_COLUMNS maps
    # it to `completed_at`), so the 201 and the History row must agree about the same event.
    assert datetime.fromisoformat(body["created_at"]) == END_OF_DUE_DAY


async def test_complete_without_the_flag_still_skips_the_missed_days(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control pair for the test above: without the flag nothing moved, so the assertions
    there describe the flag rather than the endpoint. Both ways of declining it are covered -
    `{"backdate": false}` and no body at all - which is what pins the schema default."""
    user = await make_user()
    household = await make_household(members=[user])
    explicit = await make_chore(
        household=household, title="Explicit", start_date=DUE_DAY, repeats=RepeatPeriod.daily
    )
    omitted = await make_chore(
        household=household, title="Omitted", start_date=DUE_DAY, repeats=RepeatPeriod.daily
    )
    pin_clock(monkeypatch)
    client = await auth_client(user)

    first = await client.post(f"/api/v1/chores/{explicit.id}/complete", json={"backdate": False})
    second = await client.post(f"/api/v1/chores/{omitted.id}/complete")

    assert (await closure(db_session, first.json()["id"])).completed_at == NOW
    assert (await closure(db_session, second.json()["id"])).completed_at == NOW
    # Straight past the 7th and the 8th to tomorrow, which is what the flag exists to avoid.
    assert await open_slot(db_session, explicit) == DUE_SLOT + timedelta(days=3)
    assert await open_slot(db_session, omitted) == DUE_SLOT + timedelta(days=3)


async def test_complete_backdated_twice_walks_the_chain_one_day_at_a_time(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A two-day backlog takes two backdated completions to clear, each recording its own day.
    The second lands the chore on today, at which point it is no longer overdue and the client
    stops asking the question."""
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, start_date=DUE_DAY, repeats=RepeatPeriod.daily)
    pin_clock(monkeypatch)
    client = await auth_client(user)

    await client.post(f"/api/v1/chores/{chore.id}/complete", json={"backdate": True})
    second = await client.post(f"/api/v1/chores/{chore.id}/complete", json={"backdate": True})

    assert second.status_code == 201
    assert (await closure(db_session, second.json()["id"])).completed_at == END_OF_DUE_DAY + (
        timedelta(days=1)
    )
    assert await open_slot(db_session, chore) == DUE_SLOT + timedelta(days=2)
    assert second.json()["days_until_due"] == 0
    assert second.json()["status"] == "today"


async def test_complete_backdated_clamps_to_now_for_a_chore_due_today(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flag is set and the chore is NOT overdue - deliberately the one clause left
    unsatisfied, since that is the branch the clamp exists for. The end of today is still
    ahead, so the closure is dated now rather than in the future, and now is on time anyway.
    This is why the server needs no overdue check of its own."""
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, start_date=NOW.date(), repeats=RepeatPeriod.daily)
    pin_clock(monkeypatch)
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete", json={"backdate": True})

    assert resp.status_code == 201
    assert (await closure(db_session, resp.json()["id"])).completed_at == NOW
    assert await open_slot(db_session, chore) == datetime(2026, 8, 9, tzinfo=UTC)
    assert resp.json()["days_until_due"] == 1


async def test_complete_backdated_clamps_to_now_for_an_early_completion(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The far side of the same clamp: a chore done a fortnight early must not be stamped with
    a completion time a fortnight in the future."""
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(
        household=household, start_date=date(2026, 8, 20), repeats=RepeatPeriod.daily
    )
    pin_clock(monkeypatch)
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete", json={"backdate": True})

    assert (await closure(db_session, resp.json()["id"])).completed_at == NOW
    assert await open_slot(db_session, chore) == datetime(2026, 8, 21, tzinfo=UTC)


async def test_complete_backdate_refused_for_an_unscheduled_chore(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unscheduled chore is never due, so it has no due day to be recorded against - and it
    reopens AT its completion moment, so a backdated one would reopen at the end of a day and
    collide with itself the second time it was done in that day."""
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, repeats=RepeatPeriod.manual)
    pin_clock(monkeypatch)
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete", json={"backdate": True})

    assert resp.status_code == 400
    assert "nothing to backdate" in resp.json()["detail"]
    # Refused, not "done and then errored": the slot is untouched and no history row exists.
    assert await open_slot(db_session, chore) is not None
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ChoreOccurrence)
            .where(
                ChoreOccurrence.chore_id == chore.id,
                ChoreOccurrence.status == OccurrenceStatus.done,
            )
        )
    ) == 0


async def test_complete_an_unscheduled_chore_without_the_flag_still_works(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The negative half of the refusal above: it keys off the flag, not off `repeats`.
    Without this, deleting the `payload.backdate` clause from that guard would break nothing."""
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household, repeats=RepeatPeriod.manual)
    pin_clock(monkeypatch)
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete", json={"backdate": False})

    assert resp.status_code == 201
    # Reopened at the completion moment, as an unscheduled chore always does.
    assert await open_slot(db_session, chore) == NOW


async def test_complete_backdate_refusal_precedes_the_credit_check(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both 400 clauses are violated at once, so which message comes back pins the ordering.
    The backdate refusal is a property of the *target* chore, so every caller gets the same
    actionable answer rather than one about their own request - the same reasoning that puts
    skip_chore's twin ahead of its occurrence lookup."""
    user = await make_user()
    stranger = await make_user(email="stranger@example.com")
    household = await make_household(members=[user, stranger])
    chore = await make_chore(household=household, repeats=RepeatPeriod.manual)
    pin_clock(monkeypatch)
    client = await auth_client(user)

    resp = await client.post(
        f"/api/v1/chores/{chore.id}/complete",
        json={"backdate": True, "completed_by_user_id": stranger.id},
    )

    assert resp.status_code == 400
    assert "nothing to backdate" in resp.json()["detail"]


async def test_complete_backdated_with_a_credit_records_both(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The chained-dialog contract on the wire: "I did it on Friday, and it was Anna's chore
    but I'm the one who did it" is one request carrying both facts."""
    me = await make_user(email="me@example.com")
    other = await make_user(email="other@example.com")
    household = await make_household(members=[me, other])
    chore = await make_chore(
        household=household, start_date=DUE_DAY, repeats=RepeatPeriod.daily, assignees=[other]
    )
    pin_clock(monkeypatch)
    client = await auth_client(me)

    resp = await client.post(
        f"/api/v1/chores/{chore.id}/complete",
        json={"backdate": True, "completed_by_user_id": other.id},
    )

    assert resp.status_code == 201
    closed = await closure(db_session, resp.json()["id"])
    assert closed.completed_by_user_id == other.id
    assert closed.completed_at == END_OF_DUE_DAY
    assert await open_slot(db_session, chore) == DUE_SLOT + timedelta(days=1)


async def test_complete_backdated_advances_the_rotation_once_per_tap(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clearing a two-day backlog by recording each day passes three turns, where declining the
    flag clears the same gap in one completion and passes one. Deliberate rather than
    incidental: three occurrences really did happen. `_successor_assignee` counts done rows and
    knows nothing about backdating, so nothing else here would notice this changing.

    The un-flagged control is what makes the assertion mean anything. Rotations always equal
    completions, so "three backdated completions rotate three times" is true of any three
    completions; what backdating changes is how many completions the gap costs.
    """
    a = await make_user(email="anna@example.com", first_name="Anna")
    b = await make_user(email="bob@example.com", first_name="Bob")
    c = await make_user(email="cleo@example.com", first_name="Cleo")
    household = await make_household(members=[a, b, c])

    def rotating(title: str) -> Awaitable[Chore]:
        return make_chore(
            household=household,
            title=title,
            start_date=DUE_DAY,
            repeats=RepeatPeriod.daily,
            assignment_type=AssignmentType.alphabetical,
            turn_length=1,
            assignees=[a, b, c],
            current_assignee=a,
        )

    walked_chore = await rotating("Walked")
    control = await rotating("Cleared in one")
    pin_clock(monkeypatch)
    client = await auth_client(a)

    async def on_the_hook(chore: Chore) -> int | None:
        return await db_session.scalar(
            select(ChoreOccurrence.assignee_id).where(
                ChoreOccurrence.chore_id == chore.id,
                ChoreOccurrence.status == OccurrenceStatus.open,
            )
        )

    walked = []
    for _ in range(3):
        await client.post(f"/api/v1/chores/{walked_chore.id}/complete", json={"backdate": True})
        walked.append(await on_the_hook(walked_chore))
    assert walked == [b.id, c.id, a.id]

    # The same two-day gap, declined: one completion jumps the chore past both missed days, so
    # the turn moves once and Cleo never comes up.
    await client.post(f"/api/v1/chores/{control.id}/complete")
    assert await on_the_hook(control) == b.id
    assert await open_slot(db_session, control) == DUE_SLOT + timedelta(days=3)

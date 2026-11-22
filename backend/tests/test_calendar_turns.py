"""`turns_follow_calendar` ("Ignore skipped"): a turn is `turn_length` grid slots counted
from the start date, so skips and swallowed missed days move the handover along with the
calendar instead of holding it back.

Most cases use a start date in the future, so every skip or completion advances exactly one
slot (nothing is overdue, so `advance_anchor` cannot roll) and the slot index is just "how many
closures so far". `_START` is always a Monday, which is the reporter's case: a daily chore with
a 7-slot turn that should change hands every Monday.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AssignmentType,
    Chore,
    ChoreOccurrence,
    Household,
    HouseholdLogEntry,
    OccurrenceStatus,
    RepeatPeriod,
    User,
)

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeChore = Callable[..., Awaitable[Chore]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]

_TODAY = datetime.now(UTC).date()
# The next Monday strictly after today, so the first slot is never due yet.
_START = _TODAY + timedelta(days=7 - _TODAY.weekday())
# The Monday two weeks before this week's: today is slot 14..20 on a daily grid from here.
_PAST_START = _TODAY - timedelta(days=14 + _TODAY.weekday())


async def _open(session: AsyncSession, chore_id: int) -> ChoreOccurrence:
    return (
        await session.execute(
            select(ChoreOccurrence).where(
                ChoreOccurrence.chore_id == chore_id,
                ChoreOccurrence.status == OccurrenceStatus.open,
            )
        )
    ).scalar_one()


async def _open_assignee(session: AsyncSession, chore_id: int) -> int | None:
    occ = await _open(session, chore_id)
    await session.refresh(occ)
    return occ.assignee_id


async def _three(make_user: MakeUser) -> tuple[User, User, User]:
    return (
        await make_user(email="ava@example.com", first_name="Ava"),
        await make_user(email="ben@example.com", first_name="Ben"),
        await make_user(email="cai@example.com", first_name="Cai"),
    )


async def _weekly_turns(
    make_chore: MakeChore,
    household: Household,
    pool: list[User],
    *,
    follow_calendar: bool = True,
    start: date = _START,
) -> Chore:
    return await make_chore(
        household=household,
        start_date=start,
        repeats=RepeatPeriod.daily,
        assignment_type=AssignmentType.alphabetical,
        turn_length=7,
        turns_follow_calendar=follow_calendar,
        assignees=pool,
    )


# --- skips ------------------------------------------------------------------


@pytest.mark.parametrize(("follow_calendar", "expected"), [(True, "ben"), (False, "ava")])
async def test_skipping_a_whole_week_hands_over_on_monday_only_when_following_the_calendar(
    follow_calendar: bool,
    expected: str,
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """The reported bug, and the gate on the fix: seven skips from a Monday land the open
    slot on the next Monday. Following the calendar, that is Ben's week; counting completions
    (the old rule, still the default), a skip never spends a turn, so it stays with Ava."""
    ava, ben, cai = await _three(make_user)
    household = await make_household(members=[ava, ben, cai])
    chore = await _weekly_turns(
        make_chore, household, [ava, ben, cai], follow_calendar=follow_calendar
    )
    client = await auth_client(ava)

    for _ in range(6):
        assert (await client.post(f"/api/v1/chores/{chore.id}/skip")).status_code == 201
    # Open on Sunday, slot 6: still the first turn either way.
    assert await _open_assignee(db_session, chore.id) == ava.id

    assert (await client.post(f"/api/v1/chores/{chore.id}/skip")).status_code == 201
    occ = await _open(db_session, chore.id)
    assert occ.scheduled_for.astimezone(UTC).date() == _START + timedelta(days=7)
    assert await _open_assignee(db_session, chore.id) == {"ava": ava.id, "ben": ben.id}[expected]


async def test_mixed_completions_and_skips_hand_over_on_the_calendar_boundary(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """Completions and skips are the same event here: three of each keep Ava, the seventh
    closure of either kind hands over. Counting completions, this would hand over only on the
    seventh *completion*, eleven days in."""
    ava, ben, cai = await _three(make_user)
    household = await make_household(members=[ava, ben, cai])
    chore = await _weekly_turns(make_chore, household, [ava, ben, cai])
    client = await auth_client(ava)

    for action in ["complete", "skip", "complete", "skip", "complete", "skip"]:
        assert (await client.post(f"/api/v1/chores/{chore.id}/{action}")).status_code == 201
        assert await _open_assignee(db_session, chore.id) == ava.id
    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    assert await _open_assignee(db_session, chore.id) == ben.id


async def test_a_chore_handed_back_to_the_household_stays_unassigned_until_the_boundary(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """A cleared row is an answer to respect mid-turn (as with the completion-counted turn),
    and dies on the boundary, where the strategy derives somebody again."""
    ava, ben, cai = await _three(make_user)
    household = await make_household(members=[ava, ben, cai])
    chore = await _weekly_turns(make_chore, household, [ava, ben, cai])
    occ = await _open(db_session, chore.id)
    occ.assignee_id = None
    await db_session.commit()
    client = await auth_client(ava)

    for _ in range(6):
        assert (await client.post(f"/api/v1/chores/{chore.id}/skip")).status_code == 201
        assert await _open_assignee(db_session, chore.id) is None
    assert (await client.post(f"/api/v1/chores/{chore.id}/skip")).status_code == 201
    assert await _open_assignee(db_session, chore.id) == ava.id


async def test_mid_turn_re_derives_when_the_assignee_left_the_pool(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """A row naming somebody outside the pool is a gap, not a choice: filled at once rather
    than left until Monday. Cai is a member of the household but not of the pool."""
    ava, ben, cai = await _three(make_user)
    household = await make_household(members=[ava, ben, cai])
    chore = await _weekly_turns(make_chore, household, [ava, ben])
    occ = await _open(db_session, chore.id)
    occ.assignee_id = cai.id
    await db_session.commit()
    client = await auth_client(ava)

    assert (await client.post(f"/api/v1/chores/{chore.id}/skip")).status_code == 201
    assert await _open_assignee(db_session, chore.id) == ava.id


# --- late completions -------------------------------------------------------


@pytest.mark.parametrize(("follow_calendar", "expected"), [(True, "ben"), (False, "ava")])
async def test_a_late_completion_over_several_turns_hands_over_once(
    follow_calendar: bool,
    expected: str,
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """Completing a chore left open since a Monday two weeks back swallows every missed slot,
    so the successor lands on slot 15..21 and never ON a boundary - the case a modulo test
    would miss. Two or three whole turns passed, and that is still one handover (Ben): the
    product call. Counting completions, it is the first of seven, so Ava keeps it."""
    ava, ben, cai = await _three(make_user)
    household = await make_household(members=[ava, ben, cai])
    chore = await _weekly_turns(
        make_chore, household, [ava, ben, cai], follow_calendar=follow_calendar, start=_PAST_START
    )
    client = await auth_client(ava)

    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    occ = await _open(db_session, chore.id)
    assert occ.scheduled_for.astimezone(UTC).date() == _TODAY + timedelta(days=1)
    assert await _open_assignee(db_session, chore.id) == {"ava": ava.id, "ben": ben.id}[expected]


async def test_editing_the_start_date_re_phases_the_turns(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """The phase comes from `start_date`, not from the open slot, and an edit is how an
    existing chore is put onto Mondays. Once the chore has history, a PATCH leaves the open slot
    where it is (`snap_to_slot` is the identity for an unpinned rule) and only moves the turns:
    starting six days before the open slot makes it slot 6, so the next closure is the boundary.
    Without the edit it would be slot 1, mid-turn."""
    ava, ben, cai = await _three(make_user)
    household = await make_household(members=[ava, ben, cai])
    chore = await _weekly_turns(make_chore, household, [ava, ben, cai])
    client = await auth_client(ava)

    assert (await client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    open_day = _START + timedelta(days=1)
    payload = _payload(
        household.id,
        start_date=(open_day - timedelta(days=6)).isoformat(),
        assignee_ids=[ava.id, ben.id, cai.id],
    )
    del payload["household_id"]
    assert (await client.patch(f"/api/v1/chores/{chore.id}", json=payload)).status_code == 200
    occ = await _open(db_session, chore.id)
    await db_session.refresh(occ)
    assert occ.scheduled_for.astimezone(UTC).date() == open_day
    assert occ.assignee_id == ava.id

    assert (await client.post(f"/api/v1/chores/{chore.id}/skip")).status_code == 201
    assert await _open_assignee(db_session, chore.id) == ben.id


async def test_least_done_at_a_calendar_boundary_ranks_on_real_completions_only(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """Only the timing of a turn moves to the calendar: who comes next is still ranked on work
    done. Ben does two, Ava one plus a skip. Counted honestly Ava is behind and keeps it; were
    the skip counted it would be a 2-2 tie with Ava on the hook, which `least_done` reads as a
    handover to Ben."""
    ava = await make_user(email="ava@example.com", first_name="Ava")
    ben = await make_user(email="ben@example.com", first_name="Ben")
    household = await make_household(members=[ava, ben])
    chore = await make_chore(
        household=household,
        start_date=_START,
        repeats=RepeatPeriod.daily,
        assignment_type=AssignmentType.least_done,
        turn_length=2,
        turns_follow_calendar=True,
        assignees=[ava, ben],
    )
    assert await _open_assignee(db_session, chore.id) == ava.id
    ava_client = await auth_client(ava)
    ben_client = await auth_client(ben)

    # Turn 0 (slots 0-1): Ben does both of Ava's days.
    for _ in range(2):
        assert (await ben_client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    # Boundary: Ava 0, Ben 2, so Ava is strictly behind and keeps it.
    assert await _open_assignee(db_session, chore.id) == ava.id
    # Turn 1 (slots 2-3): Ava does one, skips one.
    assert (await ava_client.post(f"/api/v1/chores/{chore.id}/complete")).status_code == 201
    assert (await ava_client.post(f"/api/v1/chores/{chore.id}/skip")).status_code == 201
    assert await _open_assignee(db_session, chore.id) == ava.id


# --- the field --------------------------------------------------------------


def _payload(household_id: int, **overrides: object) -> dict[str, object]:
    return {
        "household_id": household_id,
        "title": "Bins",
        "start_date": _START.isoformat(),
        "repeats": "daily",
        "assignment_type": "alphabetical",
        "turn_length": 7,
        "turns_follow_calendar": True,
    } | overrides


async def test_create_stores_the_flag_and_defaults_it_off(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    ava = await make_user(email="ava@example.com")
    household = await make_household(members=[ava])
    client = await auth_client(ava)

    resp = await client.post("/api/v1/chores", json=_payload(household.id))
    assert resp.status_code == 201
    assert resp.json()["turns_follow_calendar"] is True

    # Omitted: off, which is every chore that predates the field.
    payload = _payload(household.id)
    del payload["turns_follow_calendar"]
    resp = await client.post("/api/v1/chores", json=payload)
    assert resp.json()["turns_follow_calendar"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"turn_length": 1},
        {"repeats": "manual", "start_date": None},
        {"assignment_type": "manual"},
    ],
    ids=["no-turns", "unscheduled", "manual-strategy"],
)
async def test_the_flag_is_forced_off_where_it_means_nothing(
    overrides: dict[str, object],
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    """Each case changes ONE of the three conditions and keeps the other two satisfied (the
    base payload takes turns on a scheduled, rotating chore), so each pins its own clause."""
    ava = await make_user(email="ava@example.com")
    household = await make_household(members=[ava])
    client = await auth_client(ava)

    resp = await client.post("/api/v1/chores", json=_payload(household.id, **overrides))
    assert resp.status_code == 201
    assert resp.json()["turns_follow_calendar"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"turn_length": 1},
        {"repeats": "manual", "start_date": None},
        {"assignment_type": "manual"},
    ],
    ids=["no-turns", "unscheduled", "manual-strategy"],
)
async def test_an_update_forces_the_flag_off_where_it_means_nothing(
    overrides: dict[str, object],
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """The same normalisation on the PATCH path, which has its own validator call."""
    ava = await make_user(email="ava@example.com")
    household = await make_household(members=[ava])
    chore = await _weekly_turns(make_chore, household, [ava])
    client = await auth_client(ava)
    payload = _payload(household.id, assignee_ids=[ava.id], **overrides)
    del payload["household_id"]

    resp = await client.patch(f"/api/v1/chores/{chore.id}", json=payload)
    assert resp.status_code == 200
    assert resp.json()["turns_follow_calendar"] is False
    await db_session.refresh(chore)
    assert chore.turns_follow_calendar is False


async def test_update_round_trips_and_logs_the_flag(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    ava = await make_user(email="ava@example.com")
    household = await make_household(members=[ava])
    chore = await _weekly_turns(make_chore, household, [ava], follow_calendar=False)
    client = await auth_client(ava)
    payload = _payload(household.id, assignee_ids=[ava.id])
    del payload["household_id"]

    resp = await client.patch(f"/api/v1/chores/{chore.id}", json=payload)
    assert resp.status_code == 200
    assert resp.json()["turns_follow_calendar"] is True
    await db_session.refresh(chore)
    assert chore.turns_follow_calendar is True

    entry = (
        await db_session.execute(
            select(HouseholdLogEntry).order_by(HouseholdLogEntry.id.desc()).limit(1)
        )
    ).scalar_one()
    assert entry.changed_fields is not None
    assert "turns_follow_calendar" in entry.changed_fields

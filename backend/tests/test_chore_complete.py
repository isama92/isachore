from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chore, CompletedChore, Household, RepeatPeriod, User

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeChore = Callable[..., Awaitable[Chore]]
MakeCompletion = Callable[..., Awaitable[CompletedChore]]
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

    refreshed = (await db_session.execute(select(Chore).where(Chore.id == chore.id))).scalar_one()
    assert refreshed.last_completed_at is not None

    completions = (
        (
            await db_session.execute(
                select(CompletedChore).where(CompletedChore.chore_id == chore.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(completions) == 1
    assert completions[0].title == "Dishes"
    assert completions[0].completed_by_user_id == user.id


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
    make_completion: MakeCompletion,
    auth_client: AuthClient,
) -> None:
    # Simulates a concurrent double-submit: a completion already exists for the
    # occurrence the endpoint is about to record (same chore_id + scheduled_for),
    # so the unique guard yields a 409 rather than a 500.
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(household=household, start_date=today, repeats=RepeatPeriod.daily)
    occurrence = datetime(today.year, today.month, today.day, tzinfo=UTC)
    await make_completion(chore=chore, scheduled_for=occurrence)
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


async def test_second_completion_records_next_occurrence(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    today = datetime.now(UTC).date()
    chore = await make_chore(household=household, start_date=today, repeats=RepeatPeriod.daily)
    client = await auth_client(user)

    first = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert first.status_code == 201
    second = await client.post(f"/api/v1/chores/{chore.id}/complete")
    assert second.status_code == 201
    # The second completion records a later occurrence, not the same one again.
    assert second.json()["scheduled_for"] > first.json()["scheduled_for"]

from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models import (
    AssignmentType,
    Chore,
    Household,
    RepeatPeriod,
    Tag,
    User,
    household_members,
)

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeTag = Callable[..., Awaitable[Tag]]
MakeChore = Callable[..., Awaitable[Chore]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


# --- relationships ---


async def test_household_members_are_bidirectional(
    db_session, make_user: MakeUser, make_household: MakeHousehold
) -> None:
    alice = await make_user(email="alice@example.com", name="Alice")
    bob = await make_user(email="bob@example.com", name="Bob")
    household = await make_household(name="Flat 3B", members=[alice, bob])

    await db_session.refresh(household, attribute_names=["members"])
    assert {u.email for u in household.members} == {"alice@example.com", "bob@example.com"}

    result = await db_session.execute(
        select(User).options(selectinload(User.households)).where(User.id == alice.id)
    )
    assert [h.name for h in result.scalar_one().households] == ["Flat 3B"]


async def test_chore_assignees_and_tags(
    db_session,
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_tag: MakeTag,
    make_chore: MakeChore,
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(members=[alice])
    tag = await make_tag(household=household, name="deep-clean")
    chore = await make_chore(
        household=household,
        title="Scrub the tub",
        assignees=[alice],
        tags=[tag],
        repeats=RepeatPeriod.daily,
        assignment_type=AssignmentType.least_done,
    )

    assert [u.email for u in chore.assignees] == ["alice@example.com"]
    assert [t.name for t in chore.tags] == ["deep-clean"]

    result = await db_session.execute(
        select(Chore)
        .options(
            selectinload(Chore.assignees),
            selectinload(Chore.tags),
            selectinload(Chore.household),
        )
        .where(Chore.id == chore.id)
    )
    loaded = result.scalar_one()
    assert loaded.household.name == household.name
    assert loaded.repeats is RepeatPeriod.daily
    assert loaded.assignment_type is AssignmentType.least_done


# --- constraints ---


async def test_tag_name_unique_within_household(
    make_household: MakeHousehold, make_tag: MakeTag
) -> None:
    household = await make_household()
    await make_tag(household=household, name="cleaning")
    with pytest.raises(IntegrityError):
        await make_tag(household=household, name="cleaning")


async def test_tag_name_reusable_across_households(
    make_household: MakeHousehold, make_tag: MakeTag
) -> None:
    h1 = await make_household(name="H1")
    h2 = await make_household(name="H2")
    await make_tag(household=h1, name="cleaning")
    tag2 = await make_tag(household=h2, name="cleaning")
    assert tag2.id is not None


async def test_avatar_path_unique_across_users(db_session, make_user: MakeUser) -> None:
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    alice.avatar_path = "shared.webp"
    await db_session.commit()

    bob.avatar_path = "shared.webp"
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_avatar_path_allows_multiple_nulls(db_session, make_user: MakeUser) -> None:
    # "No avatar" is NULL, and Postgres treats NULLs as distinct, so the unique
    # constraint must not collide across users who haven't set a picture.
    alice = await make_user(email="alice@example.com")
    bob = await make_user(email="bob@example.com")
    assert alice.avatar_path is None
    assert bob.avatar_path is None


# --- auto-join on user creation ---


async def test_new_user_joins_default_household(
    db_session,
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    await make_household(members=[admin])
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={"email": "newbie@example.com", "name": "Newbie", "password": "password12345"},
    )
    assert resp.status_code == 201
    new_id = resp.json()["id"]

    rows = (
        await db_session.execute(
            select(household_members).where(household_members.c.user_id == new_id)
        )
    ).all()
    assert len(rows) == 1


async def test_user_creation_without_household_is_noop(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={"email": "newbie@example.com", "name": "Newbie", "password": "password12345"},
    )
    assert resp.status_code == 201

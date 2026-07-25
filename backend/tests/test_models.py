from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models import (
    AssignmentType,
    Chore,
    ChoreOccurrence,
    Household,
    OccurrenceStatus,
    RepeatPeriod,
    Tag,
    User,
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
    alice = await make_user(email="alice@example.com", first_name="Alice", last_name="A")
    bob = await make_user(email="bob@example.com", first_name="Bob", last_name="B")
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


async def test_chore_occurrence_round_trips_open_and_done(
    db_session,
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
) -> None:
    alice = await make_user(email="alice@example.com")
    household = await make_household(members=[alice])
    chore = await make_chore(household=household, assignees=[alice], with_occurrence=False)
    assert chore.turn_length == 1  # column default

    db_session.add_all(
        [
            ChoreOccurrence(
                chore_id=chore.id,
                scheduled_for=datetime(2026, 7, 20, tzinfo=UTC),
                assignee_id=alice.id,
            ),
            ChoreOccurrence(
                chore_id=chore.id,
                scheduled_for=datetime(2026, 7, 19, tzinfo=UTC),
                assignee_id=alice.id,
                status=OccurrenceStatus.done,
                title=chore.title,
                completed_by_user_id=alice.id,
                completed_at=datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
            ),
        ]
    )
    await db_session.commit()

    result = await db_session.execute(
        select(ChoreOccurrence)
        .options(selectinload(ChoreOccurrence.assignee), selectinload(ChoreOccurrence.chore))
        .where(ChoreOccurrence.chore_id == chore.id)
        .order_by(ChoreOccurrence.scheduled_for)
    )
    done, current = result.scalars().all()
    assert current.status == OccurrenceStatus.open
    assert current.assignee.email == "alice@example.com"
    assert current.title is None  # open rows read the live chore title
    assert current.chore.id == chore.id
    assert done.status == OccurrenceStatus.done
    assert done.title == chore.title
    assert done.completed_by_user_id == alice.id


async def test_chore_occurrence_rejects_duplicate_slot(
    db_session, make_household: MakeHousehold, make_chore: MakeChore
) -> None:
    # (chore_id, scheduled_for) is unique: an occurrence slot can exist only once.
    household = await make_household()
    chore = await make_chore(household=household, with_occurrence=False)
    slot = datetime(2026, 7, 20, tzinfo=UTC)
    db_session.add(
        ChoreOccurrence(
            chore_id=chore.id, scheduled_for=slot, status=OccurrenceStatus.done, title="x"
        )
    )
    await db_session.commit()
    db_session.add(ChoreOccurrence(chore_id=chore.id, scheduled_for=slot))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_chore_occurrence_allows_only_one_open_per_chore(
    db_session, make_household: MakeHousehold, make_chore: MakeChore
) -> None:
    # The partial unique index permits at most one open occurrence per chore.
    household = await make_household()
    chore = await make_chore(household=household, with_occurrence=False)
    db_session.add(
        ChoreOccurrence(chore_id=chore.id, scheduled_for=datetime(2026, 7, 20, tzinfo=UTC))
    )
    await db_session.commit()
    db_session.add(
        ChoreOccurrence(chore_id=chore.id, scheduled_for=datetime(2026, 7, 21, tzinfo=UTC))
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


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

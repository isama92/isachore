from sqlalchemy import ColumnElement, Select, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chore, Household, User, UserStatus, household_members

# Whitelisted sort keys for the household tables and the members table. Literals
# at the query-param layer make an unknown value a 422; the maps below turn a
# key into the column(s) to order by ("name" spans both member name fields).
HOUSEHOLD_SORT_COLUMNS = {
    "id": (Household.id,),
    "name": (Household.name,),
    "created_at": (Household.created_at,),
}
MEMBER_SORT_COLUMNS = {
    "id": (User.id,),
    "name": (User.first_name, User.last_name),
}


def escape_like(term: str) -> str:
    """Escape LIKE wildcards so a search term is matched literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def member_count_column() -> ColumnElement[int]:
    """Correlated subquery counting a household's active members (disabled users
    are hidden everywhere, so they don't count towards the total)."""
    return (
        select(func.count())
        .select_from(household_members)
        .join(User, User.id == household_members.c.user_id)
        .where(
            household_members.c.household_id == Household.id,
            User.status == UserStatus.active,
        )
        .correlate(Household)
        .scalar_subquery()
    )


def chore_count_column() -> ColumnElement[int]:
    """Correlated subquery counting a household's active (non-deleted) chores."""
    return (
        select(func.count())
        .select_from(Chore)
        .where(Chore.household_id == Household.id, Chore.deleted_at.is_(None))
        .correlate(Household)
        .scalar_subquery()
    )


def member_of(user_id: int) -> ColumnElement[bool]:
    """Filter selecting households the given user is a member of."""
    return Household.id.in_(
        select(household_members.c.household_id).where(household_members.c.user_id == user_id)
    )


def member_household_ids(user_id: int) -> Select[tuple[int]]:
    """Subquery of the ids of the active (non-deleted) households a user belongs to.
    The canonical scope for "chores this user can see" (used by the chores list and
    the Home due view)."""
    return (
        select(household_members.c.household_id)
        .join(Household, Household.id == household_members.c.household_id)
        .where(household_members.c.user_id == user_id, Household.deleted_at.is_(None))
    )


async def get_member_household(
    session: AsyncSession, user_id: int, household_id: int
) -> Household | None:
    """The active (non-deleted) household with this id that the user belongs to,
    or None. Used to scope chore/tag operations to a household the caller chose."""
    result = await session.execute(
        select(Household)
        .join(household_members, household_members.c.household_id == Household.id)
        .where(
            Household.id == household_id,
            Household.deleted_at.is_(None),
            household_members.c.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def is_active_member(session: AsyncSession, household_id: int, user_id: int) -> bool:
    """Whether the user is an active member of the household."""
    result = await session.execute(
        select(household_members.c.user_id)
        .join(User, User.id == household_members.c.user_id)
        .where(
            household_members.c.household_id == household_id,
            household_members.c.user_id == user_id,
            User.status == UserStatus.active,
        )
    )
    return result.first() is not None


async def add_member(session: AsyncSession, household_id: int, user_id: int) -> None:
    """Insert a household membership row."""
    await session.execute(
        insert(household_members).values(household_id=household_id, user_id=user_id)
    )


async def add_to_default_household(session: AsyncSession, user_id: int) -> None:
    """Add a freshly created user to the default (lowest-id) household.

    Best-effort: no-op when no household exists yet (e.g. in tests that don't
    seed one). Real household management is a later feature; for now every user
    lands in the single household created by the initial migration.
    """
    household_id = (
        await session.execute(select(Household.id).order_by(Household.id).limit(1))
    ).scalar_one_or_none()
    if household_id is not None:
        await add_member(session, household_id, user_id)

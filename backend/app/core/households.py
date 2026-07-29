from sqlalchemy import ColumnElement, Select, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chore, ChoreOccurrence, Household, User, UserStatus, household_members

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


def chore_scope(user_id: int, household_id: int | None) -> list[ColumnElement[bool]]:
    """Chore-level scope shared by the two occurrence views (`api/v1/home.py` and
    `api/v1/unscheduled.py`): live chores in the user's active households, optionally narrowed
    to one. A household the user cannot see yields an empty scope rather than a 403, like the
    chores list. Neither caller wants the same repeat periods, so the `repeats` predicate is
    left to them - which is the whole reason this is a list rather than a single clause."""
    scope = [
        Chore.deleted_at.is_(None),
        Chore.household_id.in_(member_household_ids(user_id)),
    ]
    if household_id is not None:
        scope.append(Chore.household_id == household_id)
    return scope


def assignee_visibility(assignee_id: list[int] | None) -> ColumnElement[bool] | None:
    """The selected members' occurrences, plus unassigned/shared ones (which belong to
    everyone), or None for no assignee filter at all. The current assignee alone decides
    visibility, so a rotating chore leaves your list the moment it hands off."""
    if not assignee_id:
        return None
    return or_(ChoreOccurrence.assignee_id.is_(None), ChoreOccurrence.assignee_id.in_(assignee_id))


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


_PERSONAL_SUFFIX = "'s place"
# Read off the column so this cannot drift if households.name is ever resized.
_NAME_MAX = Household.__table__.c.name.type.length or 255


def personal_household_name(first_name: str) -> str:
    """Name for a household belonging to one person, clipped to fit `households.name`.

    Only `db/seed.py` uses this, for the solo household it gives each seeded user;
    nothing provisions a household automatically any more, so a real user names
    their own. The clipping is therefore defensive rather than load-bearing today,
    since seed's first names are short: `households.name` is varchar(255) and
    Postgres rejects an over-long INSERT outright instead of truncating, so any
    caller passing a 255-character first name (the schema limit, should one ever
    exist again) would get an error rather than a shortened name. The suffix is
    kept whole; the name gives.
    """
    return f"{first_name[: _NAME_MAX - len(_PERSONAL_SUFFIX)]}{_PERSONAL_SUFFIX}"

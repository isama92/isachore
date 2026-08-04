from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, Select, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chore,
    ChoreOccurrence,
    Household,
    HouseholdRole,
    User,
    UserStatus,
    household_members,
)

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


# The role ladder, weakest first. This tuple is the ONLY place the ordering of
# HouseholdRole is written down; everything else asks roles_at_least, which turns a
# minimum into the set of roles that satisfy it. That is what keeps every scoped query a
# plain `role IN (...)` instead of a CASE expression, and it means inserting a new role
# into the ladder needs no change to any query.
_ROLE_LADDER: tuple[HouseholdRole, ...] = (
    HouseholdRole.helper,
    HouseholdRole.deputy,
    HouseholdRole.organiser,
)


def roles_at_least(role: HouseholdRole) -> tuple[HouseholdRole, ...]:
    """The roles granting at least everything `role` grants, itself included."""
    return _ROLE_LADDER[_ROLE_LADDER.index(role) :]


def _grants(min_role: HouseholdRole | None) -> list[ColumnElement[bool]]:
    """Role predicate for a query already joined to `household_members`, or no
    predicate at all when min_role is None (plain membership is enough)."""
    if min_role is None:
        return []
    return [household_members.c.role.in_(roles_at_least(min_role))]


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
    """Filter selecting households the given user is a member of. No role narrowing:
    every household surface is member-level to read, and its writes gate on ownership
    (`_get_owned_household`) rather than on a role."""
    return Household.id.in_(
        select(household_members.c.household_id).where(household_members.c.user_id == user_id)
    )


def member_household_ids(user_id: int, min_role: HouseholdRole | None = None) -> Select[tuple[int]]:
    """Subquery of the ids of the active (non-deleted) households a user belongs to.
    The canonical scope for "chores this user can see" (used by the chores list and
    the Home due view).

    `min_role` narrows it to the households where the user's role grants at least that
    much, which is how the role-gated read surfaces work: they return *less data* rather
    than a 403, because they all span every household at once. A deputy in one household
    and a helper in another sees the first one's statistics and simply never learns the
    second exists there. History is the one surface that combines two of these rather
    than picking one (`or_` of the deputy scope and the plain scope restricted to the
    caller's own closures), so it shows that second household - their own rows only."""
    return (
        select(household_members.c.household_id)
        .join(Household, Household.id == household_members.c.household_id)
        .where(
            household_members.c.user_id == user_id,
            Household.deleted_at.is_(None),
            *_grants(min_role),
        )
    )


def chore_scope(user_id: int, household_id: int | None) -> list[ColumnElement[bool]]:
    """Chore-level scope shared by the two occurrence views (`api/v1/home.py` and
    `api/v1/unscheduled.py`): live chores in the user's active households, optionally narrowed
    to one. A household the user cannot see yields an empty scope rather than a 403, like the
    chores list. Neither caller wants the same repeat periods, so the `repeats` predicate is
    left to them - which is the whole reason this is a list rather than a single clause.

    Deliberately takes no `min_role`: both views are open to every role, since completing a
    chore is the one thing a helper is for. Do not add one - these two views are the work
    itself, so narrowing this narrows what a helper is there to do."""
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
    session: AsyncSession,
    user_id: int,
    household_id: int,
    min_role: HouseholdRole | None = None,
) -> Household | None:
    """The active (non-deleted) household with this id that the user belongs to,
    or None. Used to scope chore/tag operations to a household the caller chose.

    Callers that pass `min_role` and turn None into a 404 are saying "you cannot see this
    household's chores/tags at all", which is right for a read. A *write* wants
    `require_role` instead, so a deputy editing a chore is told they lack the role rather
    than that the household they are looking at does not exist."""
    result = await session.execute(
        select(Household)
        .join(household_members, household_members.c.household_id == Household.id)
        .where(
            Household.id == household_id,
            Household.deleted_at.is_(None),
            household_members.c.user_id == user_id,
            *_grants(min_role),
        )
    )
    return result.scalar_one_or_none()


async def role_in_household(
    session: AsyncSession, household_id: int, user_id: int
) -> HouseholdRole | None:
    """The user's role in this household, or None when they are not a member. Does
    not care whether the household is soft-deleted; callers that need that check it."""
    role = await session.scalar(
        select(household_members.c.role).where(
            household_members.c.household_id == household_id,
            household_members.c.user_id == user_id,
        )
    )
    return None if role is None else HouseholdRole(role)


async def memberships_for(session: AsyncSession, user_id: int) -> list[tuple[int, HouseholdRole]]:
    """(household id, role) for every active household the user belongs to. Feeds
    `/auth/me`, which is what lets the frontend hide a nav item without a second
    request; the backend never trusts it, it re-checks on every call."""
    rows = await session.execute(
        select(household_members.c.household_id, household_members.c.role)
        .join(Household, Household.id == household_members.c.household_id)
        .where(household_members.c.user_id == user_id, Household.deleted_at.is_(None))
        .order_by(household_members.c.household_id)
    )
    return [(household_id, HouseholdRole(role)) for household_id, role in rows.all()]


async def require_role(
    session: AsyncSession, household_id: int, user_id: int, min_role: HouseholdRole
) -> HouseholdRole:
    """The caller's role in this household, or 403 when it does not reach `min_role`.

    Gates the household-scoped *writes* (chore and tag mutations). 403 rather than the
    404 this module uses for an invisible household: the caller is a member and can see
    the thing elsewhere in the app, so "not found" would be a lie. Callers resolve the
    household first, so a non-member has already had their 404."""
    role = await role_in_household(session, household_id, user_id)
    if role is None or role not in roles_at_least(min_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Only household {min_role}s can do this",
        )
    return role


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


async def add_member(
    session: AsyncSession, household_id: int, user_id: int, role: HouseholdRole
) -> None:
    """Insert a household membership row. `role` has no default on purpose: it is a
    permission, so every caller has to say out loud what it is granting. The column's
    server_default (helper) is the safety net for paths that bypass this function, not a
    shorthand for the ones that don't."""
    await session.execute(
        insert(household_members).values(household_id=household_id, user_id=user_id, role=role)
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

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import contains_eager, selectinload

from app.api.deps import CurrentUser, SessionDep
from app.api.v1.households import SortDir
from app.core.households import get_member_household
from app.models import Chore, Household, Tag, User, UserStatus, household_members
from app.schemas import ChoreCreate, ChoreRead, ChoreUpdate, Page

router = APIRouter()

# Whitelisted sort keys -> the column(s) to order by. "household" sorts by the
# joined household name; only these values reach the handler (the Literal below
# makes anything else a 422), so the map lookup can never KeyError.
ChoreSortBy = Literal["id", "title", "start_date", "created_at", "household"]

CHORE_SORT_COLUMNS = {
    "id": (Chore.id,),
    "title": (Chore.title,),
    "start_date": (Chore.start_date,),
    "created_at": (Chore.created_at,),
    "household": (Household.name,),
}


def _member_household_ids(user_id: int) -> Select[tuple[int]]:
    """Subquery of the ids of the active (non-deleted) households a user belongs to."""
    return (
        select(household_members.c.household_id)
        .join(Household, Household.id == household_members.c.household_id)
        .where(household_members.c.user_id == user_id, Household.deleted_at.is_(None))
    )


async def _load_chore(session: SessionDep, chore_id: int) -> Chore:
    """Reload a chore with its relationships eager-loaded (for the response)."""
    result = await session.execute(
        select(Chore)
        .options(
            selectinload(Chore.assignees),
            selectinload(Chore.tags),
            selectinload(Chore.household),
        )
        .where(Chore.id == chore_id)
    )
    return result.scalar_one()


async def _get_user_chore_or_404(session: SessionDep, user: User, chore_id: int) -> Chore:
    """A non-deleted chore in one of the user's active households, or 404."""
    result = await session.execute(
        select(Chore)
        .join(Household, Household.id == Chore.household_id)
        .join(household_members, household_members.c.household_id == Household.id)
        .options(
            selectinload(Chore.assignees),
            selectinload(Chore.tags),
            selectinload(Chore.household),
        )
        .where(
            Chore.id == chore_id,
            Chore.deleted_at.is_(None),
            Household.deleted_at.is_(None),
            household_members.c.user_id == user.id,
        )
    )
    chore = result.scalar_one_or_none()
    if chore is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chore not found")
    return chore


async def _resolve_household_or_404(
    session: SessionDep, user: User, household_id: int
) -> Household:
    household = await get_member_household(session, user.id, household_id)
    if household is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Household not found")
    return household


async def _resolve_assignees(
    session: SessionDep, household: Household, ids: list[int]
) -> list[User]:
    if not ids:
        return []
    result = await session.execute(
        select(User)
        .join(household_members, household_members.c.user_id == User.id)
        .where(
            household_members.c.household_id == household.id,
            User.id.in_(ids),
            User.status == UserStatus.active,
        )
    )
    users = list(result.scalars())
    if len(users) != len(set(ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assignees must be members of your household",
        )
    return users


async def _resolve_tags(session: SessionDep, household: Household, ids: list[int]) -> list[Tag]:
    if not ids:
        return []
    result = await session.execute(
        select(Tag).where(Tag.household_id == household.id, Tag.id.in_(ids))
    )
    tags = list(result.scalars())
    if len(tags) != len(set(ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tags must belong to your household",
        )
    return tags


@router.post("", response_model=ChoreRead, status_code=status.HTTP_201_CREATED)
async def create_chore(payload: ChoreCreate, user: CurrentUser, session: SessionDep) -> Chore:
    household = await _resolve_household_or_404(session, user, payload.household_id)
    assignees = await _resolve_assignees(session, household, payload.assignee_ids)
    tags = await _resolve_tags(session, household, payload.tag_ids)
    chore = Chore(
        household_id=household.id,
        title=payload.title,
        description=payload.description,
        start_date=payload.start_date,
        repeats=payload.repeats,
        assignment_type=payload.assignment_type,
        assignees=assignees,
        tags=tags,
    )
    session.add(chore)
    await session.commit()
    return await _load_chore(session, chore.id)


@router.get("", response_model=Page[ChoreRead])
async def list_chores(
    user: CurrentUser,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: ChoreSortBy = "start_date",
    sort_dir: SortDir = "asc",
    household_id: Annotated[int | None, Query(ge=1)] = None,
) -> Page[ChoreRead]:
    # Scope to non-deleted chores in the user's active households; an optional
    # household_id narrows to one of them (a non-member id yields an empty page).
    filters = [Chore.deleted_at.is_(None), Chore.household_id.in_(_member_household_ids(user.id))]
    if household_id is not None:
        filters.append(Chore.household_id == household_id)

    total = await session.scalar(select(func.count()).select_from(Chore).where(*filters)) or 0

    descending = sort_dir == "desc"
    order_by = [col.desc() if descending else col.asc() for col in CHORE_SORT_COLUMNS[sort_by]]
    order_by.append(Chore.id.desc() if descending else Chore.id.asc())  # stable tiebreaker

    result = await session.execute(
        select(Chore)
        .join(Household, Household.id == Chore.household_id)  # to-one: no row multiplication
        .options(
            selectinload(Chore.assignees),
            selectinload(Chore.tags),
            contains_eager(Chore.household),
        )
        .where(*filters)
        .order_by(*order_by)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = [ChoreRead.model_validate(chore) for chore in result.scalars().all()]
    return Page[ChoreRead](items=items, total=total, page=page, page_size=page_size)


@router.get("/{chore_id}", response_model=ChoreRead)
async def get_chore(chore_id: int, user: CurrentUser, session: SessionDep) -> Chore:
    return await _get_user_chore_or_404(session, user, chore_id)


@router.patch("/{chore_id}", response_model=ChoreRead)
async def update_chore(
    chore_id: int, payload: ChoreUpdate, user: CurrentUser, session: SessionDep
) -> Chore:
    chore = await _get_user_chore_or_404(session, user, chore_id)
    # The household is fixed at creation; re-validate assignees/tags against it.
    assignees = await _resolve_assignees(session, chore.household, payload.assignee_ids)
    tags = await _resolve_tags(session, chore.household, payload.tag_ids)
    chore.title = payload.title
    chore.description = payload.description
    chore.start_date = payload.start_date
    chore.repeats = payload.repeats
    chore.assignment_type = payload.assignment_type
    chore.assignees = assignees
    chore.tags = tags
    await session.commit()
    return await _load_chore(session, chore.id)


@router.delete("/{chore_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chore(chore_id: int, user: CurrentUser, session: SessionDep) -> None:
    chore = await _get_user_chore_or_404(session, user, chore_id)
    chore.deleted_at = datetime.now(UTC)
    await session.commit()

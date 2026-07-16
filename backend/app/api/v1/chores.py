from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentHousehold, SessionDep
from app.models import Chore, Household, Tag, User, household_members
from app.schemas import ChoreCreate, ChoreRead

router = APIRouter()


async def _get_chore_or_404(session: SessionDep, household_id: int, chore_id: int) -> Chore:
    result = await session.execute(
        select(Chore)
        .options(selectinload(Chore.assignees), selectinload(Chore.tags))
        .where(Chore.id == chore_id, Chore.household_id == household_id)
    )
    chore = result.scalar_one_or_none()
    if chore is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chore not found")
    return chore


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
            User.is_active.is_(True),
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
async def create_chore(
    payload: ChoreCreate, household: CurrentHousehold, session: SessionDep
) -> Chore:
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
    return await _get_chore_or_404(session, household.id, chore.id)


@router.get("", response_model=list[ChoreRead])
async def list_chores(household: CurrentHousehold, session: SessionDep) -> list[Chore]:
    result = await session.execute(
        select(Chore)
        .options(selectinload(Chore.assignees), selectinload(Chore.tags))
        .where(Chore.household_id == household.id)
        .order_by(Chore.id)
    )
    return list(result.scalars())


@router.delete("/{chore_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chore(chore_id: int, household: CurrentHousehold, session: SessionDep) -> None:
    chore = await _get_chore_or_404(session, household.id, chore_id)
    await session.delete(chore)
    await session.commit()

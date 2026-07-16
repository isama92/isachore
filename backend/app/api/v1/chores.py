from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentHousehold, SessionDep
from app.models import Chore
from app.schemas import ChoreRead

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

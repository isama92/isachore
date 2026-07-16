from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep
from app.models import Household, household_members
from app.schemas import HouseholdRead

router = APIRouter()


@router.get("", response_model=list[HouseholdRead])
async def list_households(user: CurrentUser, session: SessionDep) -> list[Household]:
    result = await session.execute(
        select(Household)
        .join(household_members, household_members.c.household_id == Household.id)
        .where(household_members.c.user_id == user.id)
        .options(selectinload(Household.members))
        .order_by(Household.id)
    )
    return list(result.scalars())

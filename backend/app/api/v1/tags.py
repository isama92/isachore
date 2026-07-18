from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep, get_current_household
from app.core.households import get_member_household
from app.models import Tag
from app.schemas import TagRead

router = APIRouter()


@router.get("", response_model=list[TagRead])
async def list_tags(
    user: CurrentUser,
    session: SessionDep,
    household_id: Annotated[int | None, Query(ge=1)] = None,
) -> list[Tag]:
    # Chores can belong to any of the caller's households, so the tag picker must
    # be able to load a chosen household's tags; without household_id we fall back
    # to the caller's current (lowest-id) household.
    if household_id is None:
        household = await get_current_household(user, session)
    else:
        household = await get_member_household(session, user.id, household_id)
        if household is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Household not found")
    result = await session.execute(
        select(Tag).where(Tag.household_id == household.id).order_by(Tag.id)
    )
    return list(result.scalars())

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentHousehold, SessionDep
from app.models import Tag
from app.schemas import TagRead

router = APIRouter()


@router.get("", response_model=list[TagRead])
async def list_tags(household: CurrentHousehold, session: SessionDep) -> list[Tag]:
    result = await session.execute(
        select(Tag).where(Tag.household_id == household.id).order_by(Tag.id)
    )
    return list(result.scalars())

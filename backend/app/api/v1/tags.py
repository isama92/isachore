from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, SessionDep, get_current_household
from app.core.households import get_member_household
from app.models import Household, Tag, User, household_members
from app.schemas import TagCreate, TagRead, TagUpdate

router = APIRouter()

# The (household_id, name) unique constraint means two tags can't share a name
# within one household; surface that as a 409 rather than a 500.
_duplicate_name_exc = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="A tag with this name already exists"
)


async def _get_member_tag_or_404(session: SessionDep, user: User, tag_id: int) -> Tag:
    """A tag in one of the user's active (non-deleted) households, or 404.

    Membership is the authorization gate: a tag in a household the caller does
    not belong to simply 404s (mirrors _get_user_chore_or_404 in chores.py)."""
    result = await session.execute(
        select(Tag)
        .join(Household, Household.id == Tag.household_id)
        .join(household_members, household_members.c.household_id == Household.id)
        .where(
            Tag.id == tag_id,
            Household.deleted_at.is_(None),
            household_members.c.user_id == user.id,
        )
    )
    tag = result.scalar_one_or_none()
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    return tag


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


@router.post("", response_model=TagRead, status_code=status.HTTP_201_CREATED)
async def create_tag(payload: TagCreate, user: CurrentUser, session: SessionDep) -> Tag:
    household = await get_member_household(session, user.id, payload.household_id)
    if household is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Household not found")
    tag = Tag(household_id=household.id, name=payload.name, color=payload.color)
    session.add(tag)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _duplicate_name_exc from None
    return tag


@router.get("/{tag_id}", response_model=TagRead)
async def get_tag(tag_id: int, user: CurrentUser, session: SessionDep) -> Tag:
    return await _get_member_tag_or_404(session, user, tag_id)


@router.patch("/{tag_id}", response_model=TagRead)
async def update_tag(
    tag_id: int, payload: TagUpdate, user: CurrentUser, session: SessionDep
) -> Tag:
    tag = await _get_member_tag_or_404(session, user, tag_id)
    tag.name = payload.name
    tag.color = payload.color
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _duplicate_name_exc from None
    return tag


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(tag_id: int, user: CurrentUser, session: SessionDep) -> None:
    # Hard delete: chore_tags rows cascade, so the tag detaches from any chores.
    tag = await _get_member_tag_or_404(session, user, tag_id)
    await session.delete(tag)
    await session.commit()

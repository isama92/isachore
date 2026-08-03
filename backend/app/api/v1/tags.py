from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, SessionDep, get_current_household
from app.api.v1.households import SortDir
from app.core.households import get_member_household, require_role
from app.models import Household, HouseholdRole, Tag, User, household_members
from app.schemas import Page, TagCreate, TagRead, TagUpdate

router = APIRouter()

# Whitelisted sort keys -> the column(s) to order by; the Literal makes anything
# else a 422, so the map lookup can never KeyError (mirrors the chores router).
TagSortBy = Literal["id", "name", "created_at"]

TAG_SORT_COLUMNS = {
    "id": (Tag.id,),
    "name": (Tag.name,),
    "created_at": (Tag.created_at,),
}

# The (household_id, name) unique constraint means two tags can't share a name
# within one household; surface that as a 409 rather than a 500.
_duplicate_name_exc = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="A tag with this name already exists"
)


async def _get_organiser_tag_or_error(session: SessionDep, user: User, tag_id: int) -> Tag:
    """A tag in one of the user's active (non-deleted) households (404 otherwise), where
    they are an organiser (403 otherwise).

    Unlike chores, *every* route in this router needs the role, reads included: tags exist to
    organise the management pages, and no view a non-organiser can reach offers a tag to filter
    or pick from, so there is no read-open / write-gated split worth making here.

    Note this is about the surface, not about secrecy: `ChoreRead.tags` still carries a chore's
    tags to any member through `GET /chores/{id}`, which is open to every role on purpose (the
    description dialog). Narrowing that payload is a separate item in README's todo. Do not
    justify this gate by claiming tag names are hidden - they are not, and the next person to
    check will find that out."""
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
    await require_role(session, tag.household_id, user.id, HouseholdRole.organiser)
    return tag


@router.get("", response_model=Page[TagRead])
async def list_tags(
    user: CurrentUser,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: TagSortBy = "name",
    sort_dir: SortDir = "asc",
    household_id: Annotated[int | None, Query(ge=1)] = None,
) -> Page[TagRead]:
    # Tags are per-household, and only organisers have them, so both resolutions are
    # narrowed to the households the caller organises: an explicit household_id must be one
    # of those, and without one we fall back to their lowest-id organised household rather
    # than their lowest-id household outright, which would hand a deputy the tags of a
    # household they cannot manage. (The chore tag picker also loads a chosen household's
    # tags this way, and it only ever renders on organiser-gated pages.)
    if household_id is None:
        household = await get_current_household(user, session, HouseholdRole.organiser)
    else:
        household = await get_member_household(
            session, user.id, household_id, HouseholdRole.organiser
        )
        if household is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Household not found")

    total = (
        await session.scalar(
            select(func.count()).select_from(Tag).where(Tag.household_id == household.id)
        )
        or 0
    )

    descending = sort_dir == "desc"
    order_by = [col.desc() if descending else col.asc() for col in TAG_SORT_COLUMNS[sort_by]]
    order_by.append(Tag.id.desc() if descending else Tag.id.asc())  # stable tiebreaker

    result = await session.execute(
        select(Tag)
        .where(Tag.household_id == household.id)
        .order_by(*order_by)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = [TagRead.model_validate(tag) for tag in result.scalars().all()]
    return Page[TagRead](items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=TagRead, status_code=status.HTTP_201_CREATED)
async def create_tag(payload: TagCreate, user: CurrentUser, session: SessionDep) -> Tag:
    household = await get_member_household(session, user.id, payload.household_id)
    if household is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Household not found")
    await require_role(session, household.id, user.id, HouseholdRole.organiser)
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
    return await _get_organiser_tag_or_error(session, user, tag_id)


@router.patch("/{tag_id}", response_model=TagRead)
async def update_tag(
    tag_id: int, payload: TagUpdate, user: CurrentUser, session: SessionDep
) -> Tag:
    tag = await _get_organiser_tag_or_error(session, user, tag_id)
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
    tag = await _get_organiser_tag_or_error(session, user, tag_id)
    await session.delete(tag)
    await session.commit()

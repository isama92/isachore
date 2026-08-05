from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import AdminUser, SessionDep
from app.api.v1.households import (
    HouseholdSortBy,
    MemberSortBy,
    SortDir,
    apply_timezone_change,
    build_household_page,
    build_members_page,
    commit_household_update,
    load_household_read,
    remove_member,
    set_household_admin,
    set_member_role,
)
from app.core.households import add_member
from app.models import Household, HouseholdRole
from app.schemas import (
    HouseholdCreate,
    HouseholdListRead,
    HouseholdMemberRoleRead,
    HouseholdMemberUpdate,
    HouseholdUpdate,
    Page,
)

router = APIRouter()

# Admins can narrow the listing to active (not deleted), soft-deleted, or all.
HouseholdStatusFilter = Literal["active", "deleted", "all"]


async def _get_household_or_404(session: SessionDep, household_id: int) -> Household:
    """Any household by id, including soft-deleted ones (admins manage all)."""
    household = await session.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Household not found")
    return household


@router.get("", response_model=Page[HouseholdListRead])
async def list_households(
    _: AdminUser,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: HouseholdSortBy = "created_at",
    sort_dir: SortDir = "desc",
    name: Annotated[str | None, Query(max_length=255)] = None,
    # Named status_filter so it doesn't shadow the fastapi `status` module; the
    # query-string key stays `status` via the alias.
    status_filter: Annotated[HouseholdStatusFilter, Query(alias="status")] = "active",
) -> Page[HouseholdListRead]:
    if status_filter == "active":
        extra_filters = [Household.deleted_at.is_(None)]
    elif status_filter == "deleted":
        extra_filters = [Household.deleted_at.is_not(None)]
    else:
        extra_filters = []
    return await build_household_page(
        session,
        extra_filters=extra_filters,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        name=name,
    )


@router.post("", response_model=HouseholdListRead, status_code=status.HTTP_201_CREATED)
async def create_household(
    payload: HouseholdCreate, admin: AdminUser, session: SessionDep
) -> HouseholdListRead:
    # admin_id is required, and it must reference a member, so the creating admin
    # becomes the household's owner and first member (an organiser, as owners are).
    # They (or another admin) can transfer ownership once real members are added.
    household = Household(name=payload.name, admin_id=admin.id, timezone=payload.timezone)
    session.add(household)
    await session.flush()
    await add_member(session, household.id, admin.id, HouseholdRole.organiser)
    await session.commit()
    return await load_household_read(session, household.id)


@router.get("/{household_id}", response_model=HouseholdListRead)
async def get_household(household_id: int, _: AdminUser, session: SessionDep) -> HouseholdListRead:
    return await load_household_read(session, household_id)


@router.patch("/{household_id}", response_model=HouseholdListRead)
async def update_household(
    household_id: int, payload: HouseholdUpdate, _: AdminUser, session: SessionDep
) -> HouseholdListRead:
    household = await _get_household_or_404(session, household_id)
    if payload.name is not None:
        household.name = payload.name
    if payload.admin_id is not None:
        await set_household_admin(session, household, payload.admin_id)
    rescheduled = await apply_timezone_change(session, household, payload.timezone)
    await commit_household_update(session, rescheduled=rescheduled)
    return await load_household_read(session, household.id)


@router.delete("/{household_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_household(household_id: int, _: AdminUser, session: SessionDep) -> None:
    household = await _get_household_or_404(session, household_id)
    if household.deleted_at is None:
        household.deleted_at = datetime.now(UTC)
        await session.commit()


@router.post("/{household_id}/restore", response_model=HouseholdListRead)
async def restore_household(
    household_id: int, _: AdminUser, session: SessionDep
) -> HouseholdListRead:
    household = await _get_household_or_404(session, household_id)
    household.deleted_at = None
    await session.commit()
    return await load_household_read(session, household.id)


@router.get("/{household_id}/members", response_model=Page[HouseholdMemberRoleRead])
async def list_household_members(
    household_id: int,
    _: AdminUser,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: MemberSortBy = "name",
    sort_dir: SortDir = "asc",
    name: Annotated[str | None, Query(max_length=255)] = None,
) -> Page[HouseholdMemberRoleRead]:
    await _get_household_or_404(session, household_id)
    return await build_members_page(
        session,
        household_id=household_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        name=name,
    )


@router.patch("/{household_id}/members/{user_id}", response_model=HouseholdMemberRoleRead)
async def update_household_member(
    household_id: int,
    user_id: int,
    payload: HouseholdMemberUpdate,
    _: AdminUser,
    session: SessionDep,
) -> HouseholdMemberRoleRead:
    """Set a member's role from the admin surface. Any of the three, on any active member.

    No organiser asymmetry here, unlike the user surface: that rule exists so an organiser
    cannot grow the set of people who could demote *them*, which is a rule about a household
    member and does not describe a site admin. An operator on this page can already transfer
    the household and remove members, so withholding the organiser role would be arbitrary.

    Resolves through `_get_household_or_404`, so it reaches soft-deleted households like the
    other routes here - a role is worth fixing before restoring one.
    """
    household = await _get_household_or_404(session, household_id)
    return await set_member_role(session, household, user_id, payload.role)


@router.delete("/{household_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_household_member(
    household_id: int, user_id: int, _: AdminUser, session: SessionDep
) -> None:
    await _get_household_or_404(session, household_id)
    await remove_member(session, household_id, user_id)

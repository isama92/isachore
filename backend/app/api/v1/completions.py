from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep
from app.api.v1.households import SortDir
from app.core.chores import days_late
from app.core.households import member_household_ids
from app.models import Chore, CompletedChore, Household, User, UserStatus, household_members
from app.schemas import HistoryEntryRead, HistoryFilterOptions, Page
from app.schemas.chore import ChoreHouseholdRead
from app.schemas.household import HouseholdMemberRead

router = APIRouter()

# Whitelisted sort keys -> the column(s) to order by. Only these values reach the
# handler (the Literal makes anything else a 422), so the map can never KeyError.
# History defaults to the completion time, most recent first.
CompletionSortBy = Literal["created_at", "title"]

COMPLETION_SORT_COLUMNS = {
    "created_at": (CompletedChore.created_at,),
    "title": (CompletedChore.title,),
}


@router.get("/filters", response_model=HistoryFilterOptions)
async def completion_filters(user: CurrentUser, session: SessionDep) -> HistoryFilterOptions:
    """The option lists for the History filters: the households the user belongs
    to, and the distinct active members across them (candidate completers)."""
    households = (
        (
            await session.execute(
                select(Household)
                .where(Household.id.in_(member_household_ids(user.id)))
                .order_by(Household.name, Household.id)
            )
        )
        .scalars()
        .all()
    )
    # distinct() dedupes a member who is shared across two of the user's households
    # (the household_members join would otherwise yield them once per household).
    members = (
        (
            await session.execute(
                select(User)
                .join(household_members, household_members.c.user_id == User.id)
                .where(
                    household_members.c.household_id.in_(member_household_ids(user.id)),
                    User.status == UserStatus.active,
                )
                .order_by(User.first_name, User.last_name, User.id)
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    return HistoryFilterOptions(
        households=[ChoreHouseholdRead.model_validate(h) for h in households],
        members=[HouseholdMemberRead.model_validate(m) for m in members],
    )


@router.get("", response_model=Page[HistoryEntryRead])
async def list_completions(
    user: CurrentUser,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: CompletionSortBy = "created_at",
    sort_dir: SortDir = "desc",
    user_id: Annotated[int | None, Query(ge=1)] = None,
    household_id: Annotated[int | None, Query(ge=1)] = None,
) -> Page[HistoryEntryRead]:
    """Completed-chore history across the user's active households (so housemates'
    completions show too). Optional user_id / household_id narrow the list; a
    non-member household or a stranger's id yields an empty page. Completions of
    soft-deleted chores are kept (the title is snapshotted for exactly this and
    the chore row still resolves the household join)."""
    # completed_chores has no household_id of its own, so scope by joining to the
    # chore and filtering on its household. No Chore.deleted_at filter: history
    # outlives a soft-deleted chore.
    filters = [Chore.household_id.in_(member_household_ids(user.id))]
    if household_id is not None:
        filters.append(Chore.household_id == household_id)
    if user_id is not None:
        filters.append(CompletedChore.completed_by_user_id == user_id)

    total = (
        await session.scalar(
            select(func.count())
            .select_from(CompletedChore)
            .join(Chore, Chore.id == CompletedChore.chore_id)
            .where(*filters)
        )
        or 0
    )

    descending = sort_dir == "desc"
    order_by = [col.desc() if descending else col.asc() for col in COMPLETION_SORT_COLUMNS[sort_by]]
    order_by.append(CompletedChore.id.desc() if descending else CompletedChore.id.asc())

    result = await session.execute(
        select(CompletedChore, Household, User)
        .join(Chore, Chore.id == CompletedChore.chore_id)  # to-one: no row multiplication
        .join(Household, Household.id == Chore.household_id)
        .outerjoin(User, User.id == CompletedChore.completed_by_user_id)  # completer may be NULL
        .where(*filters)
        .order_by(*order_by)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = [
        HistoryEntryRead(
            id=completion.id,
            title=completion.title,
            scheduled_for=completion.scheduled_for,
            completed_at=completion.created_at,
            days_late=days_late(completion.scheduled_for, completion.created_at),
            completed_by=HouseholdMemberRead.model_validate(completer) if completer else None,
            household=ChoreHouseholdRead.model_validate(household),
        )
        for completion, household, completer in result.all()
    ]
    return Page[HistoryEntryRead](items=items, total=total, page=page, page_size=page_size)


@router.delete("/{completion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def undo_completion(completion_id: int, user: CurrentUser, session: SessionDep) -> None:
    """Undo a completion: delete the record and roll the chore's schedule back.
    Only the person who recorded the completion may undo it. Deleting the latest
    completion reverts last_completed_at to the prior one (the chore becomes due
    again); deleting an older one only edits history."""
    # Scope to the user's active households (same scope as the list): a completion
    # outside it, or a missing id, is a 404.
    completion = (
        await session.execute(
            select(CompletedChore)
            .join(Chore, Chore.id == CompletedChore.chore_id)
            .options(selectinload(CompletedChore.chore))
            .where(
                CompletedChore.id == completion_id,
                Chore.household_id.in_(member_household_ids(user.id)),
            )
        )
    ).scalar_one_or_none()
    if completion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Completion not found")
    if completion.completed_by_user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only undo your own completions",
        )

    chore = completion.chore
    await session.delete(completion)
    await session.flush()  # so the deleted row is excluded from the MAX below
    # Re-anchor the denormalised last_completed_at to the latest remaining
    # completion (NULL if none remain -> the chore reverts to never-completed).
    chore.last_completed_at = await session.scalar(
        select(func.max(CompletedChore.created_at)).where(CompletedChore.chore_id == chore.id)
    )
    await session.commit()

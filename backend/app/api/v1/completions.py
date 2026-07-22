from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, SessionDep
from app.api.v1.households import SortDir
from app.core.chores import days_late
from app.core.households import member_household_ids
from app.models import (
    Chore,
    ChoreOccurrence,
    Household,
    OccurrenceStatus,
    User,
    UserStatus,
    household_members,
)
from app.schemas import HistoryEntryRead, HistoryFilterOptions, Page
from app.schemas.chore import ChoreHouseholdRead
from app.schemas.household import HouseholdMemberRead

router = APIRouter()

# Whitelisted sort keys -> the column(s) to order by. Only these values reach the
# handler (the Literal makes anything else a 422), so the map can never KeyError.
# History defaults to the completion time, most recent first. The API key stays
# "created_at" for stability; it orders by the occurrence's completion timestamp.
CompletionSortBy = Literal["created_at", "title"]

COMPLETION_SORT_COLUMNS = {
    "created_at": (ChoreOccurrence.completed_at,),
    "title": (ChoreOccurrence.title,),
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
    completions show too). Reads the `done` occurrences of the merged occurrences
    table. Optional user_id / household_id narrow the list; a non-member household or a
    stranger's id yields an empty page. History of soft-deleted chores is kept (the
    title is snapshotted for exactly this and the chore row still resolves the join)."""
    # An occurrence has no household_id of its own, so scope by joining to the chore
    # and filtering on its household. No Chore.deleted_at filter: history outlives a
    # soft-deleted chore.
    filters = [
        ChoreOccurrence.status == OccurrenceStatus.done,
        Chore.household_id.in_(member_household_ids(user.id)),
    ]
    if household_id is not None:
        filters.append(Chore.household_id == household_id)
    if user_id is not None:
        filters.append(ChoreOccurrence.completed_by_user_id == user_id)

    total = (
        await session.scalar(
            select(func.count())
            .select_from(ChoreOccurrence)
            .join(Chore, Chore.id == ChoreOccurrence.chore_id)
            .where(*filters)
        )
        or 0
    )

    descending = sort_dir == "desc"
    order_by = [col.desc() if descending else col.asc() for col in COMPLETION_SORT_COLUMNS[sort_by]]
    order_by.append(ChoreOccurrence.id.desc() if descending else ChoreOccurrence.id.asc())

    result = await session.execute(
        select(ChoreOccurrence, Household, User)
        .join(Chore, Chore.id == ChoreOccurrence.chore_id)  # to-one: no row multiplication
        .join(Household, Household.id == Chore.household_id)
        .outerjoin(User, User.id == ChoreOccurrence.completed_by_user_id)  # completer may be NULL
        .where(*filters)
        .order_by(*order_by)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = [
        HistoryEntryRead(
            id=occ.id,
            title=occ.title,
            scheduled_for=occ.scheduled_for,
            completed_at=occ.completed_at,
            days_late=days_late(occ.scheduled_for, occ.completed_at),
            completed_by=HouseholdMemberRead.model_validate(completer) if completer else None,
            household=ChoreHouseholdRead.model_validate(household),
        )
        for occ, household, completer in result.all()
    ]
    return Page[HistoryEntryRead](items=items, total=total, page=page, page_size=page_size)


@router.delete("/{completion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def undo_completion(completion_id: int, user: CurrentUser, session: SessionDep) -> None:
    """Undo a completion (identified by its done-occurrence id). Only the user the
    completion is credited to (completed_by) may undo it; the occurrence stores no
    separate record of who submitted it, so someone who completes a chore on another
    member's behalf cannot undo it themselves.
    Undoing the chore's latest completion reopens that occurrence
    (deleting the successor open occurrence first) so the chore is due again with its
    original assignee; undoing an older one just removes that history row."""
    # Scope to the user's active households (same scope as the list): a done occurrence
    # outside it, or a missing id, is a 404.
    occ = (
        await session.execute(
            select(ChoreOccurrence)
            .join(Chore, Chore.id == ChoreOccurrence.chore_id)
            .where(
                ChoreOccurrence.id == completion_id,
                ChoreOccurrence.status == OccurrenceStatus.done,
                Chore.household_id.in_(member_household_ids(user.id)),
            )
        )
    ).scalar_one_or_none()
    if occ is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Completion not found")
    if occ.completed_by_user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only undo your own completions",
        )

    # Is this the chore's most recent completion? (scheduled_for is unique per chore.)
    latest_done = await session.scalar(
        select(func.max(ChoreOccurrence.scheduled_for)).where(
            ChoreOccurrence.chore_id == occ.chore_id,
            ChoreOccurrence.status == OccurrenceStatus.done,
        )
    )
    if occ.scheduled_for == latest_done:
        # Reopen it: delete the successor open occurrence first (freeing the
        # one-open-per-chore slot), then flip this row back to open with its assignee.
        successor = (
            await session.execute(
                select(ChoreOccurrence).where(
                    ChoreOccurrence.chore_id == occ.chore_id,
                    ChoreOccurrence.status == OccurrenceStatus.open,
                )
            )
        ).scalar_one_or_none()
        if successor is not None:
            await session.delete(successor)
            await session.flush()
        occ.status = OccurrenceStatus.open
        occ.completed_by_user_id = None
        occ.completed_at = None
        occ.title = None
    else:
        # An older completion: a history edit, the current open occurrence stands.
        await session.delete(occ)
    await session.commit()

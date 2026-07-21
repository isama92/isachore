from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import contains_eager, selectinload

from app.api.deps import CurrentUser, SessionDep
from app.api.v1.households import SortDir
from app.core.assignment import initial_assignee, next_assignee, should_reassign
from app.core.chores import days_until_due, due_status, first_occurrence, next_occurrence_after
from app.core.households import get_member_household, member_household_ids
from app.models import (
    AssignmentType,
    Chore,
    ChoreOccurrence,
    Household,
    OccurrenceStatus,
    RepeatPeriod,
    Tag,
    User,
    UserStatus,
    household_members,
)
from app.schemas import (
    ChoreCreate,
    ChoreRead,
    ChoreUpdate,
    CompleteChoreRequest,
    CompletionRead,
    Page,
)

router = APIRouter()

# Whitelisted sort keys -> the column(s) to order by. "household" sorts by the
# joined household name; only these values reach the handler (the Literal below
# makes anything else a 422), so the map lookup can never KeyError.
ChoreSortBy = Literal["id", "title", "start_date", "created_at", "household"]

CHORE_SORT_COLUMNS = {
    "id": (Chore.id,),
    "title": (Chore.title,),
    "start_date": (Chore.start_date,),
    "created_at": (Chore.created_at,),
    "household": (Household.name,),
}


async def _open_occurrence(session: SessionDep, chore_id: int) -> ChoreOccurrence | None:
    """The chore's single open occurrence (the current due one), or None - queried
    explicitly rather than via a relationship so it never reads a stale cached row."""
    return (
        await session.execute(
            select(ChoreOccurrence).where(
                ChoreOccurrence.chore_id == chore_id,
                ChoreOccurrence.status == OccurrenceStatus.open,
            )
        )
    ).scalar_one_or_none()


async def _attach_current_assignee(session: SessionDep, chores: list[Chore]) -> None:
    """Set each chore's `current_assignee` (a transient attribute ChoreRead reads) to
    its open occurrence's assignee, in one batched query. None when the chore is
    unassigned/shared or has no open occurrence (a completed one-off)."""
    if not chores:
        return
    rows = (
        (
            await session.execute(
                select(ChoreOccurrence)
                .options(selectinload(ChoreOccurrence.assignee))
                .where(
                    ChoreOccurrence.chore_id.in_([c.id for c in chores]),
                    ChoreOccurrence.status == OccurrenceStatus.open,
                )
            )
        )
        .scalars()
        .all()
    )
    assignee_by_chore = {occ.chore_id: occ.assignee for occ in rows}
    for chore in chores:
        chore.current_assignee = assignee_by_chore.get(chore.id)


async def _load_chore(session: SessionDep, chore_id: int) -> Chore:
    """Reload a chore with its relationships eager-loaded (for the response)."""
    result = await session.execute(
        select(Chore)
        .options(
            selectinload(Chore.assignees),
            selectinload(Chore.tags),
            selectinload(Chore.household),
        )
        .where(Chore.id == chore_id)
    )
    chore = result.scalar_one()
    await _attach_current_assignee(session, [chore])
    return chore


async def _get_user_chore_or_404(session: SessionDep, user: User, chore_id: int) -> Chore:
    """A non-deleted chore in one of the user's active households, or 404."""
    result = await session.execute(
        select(Chore)
        .join(Household, Household.id == Chore.household_id)
        .join(household_members, household_members.c.household_id == Household.id)
        .options(
            selectinload(Chore.assignees),
            selectinload(Chore.tags),
            selectinload(Chore.household),
        )
        .where(
            Chore.id == chore_id,
            Chore.deleted_at.is_(None),
            Household.deleted_at.is_(None),
            household_members.c.user_id == user.id,
        )
    )
    chore = result.scalar_one_or_none()
    if chore is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chore not found")
    return chore


async def _resolve_household_or_404(
    session: SessionDep, user: User, household_id: int
) -> Household:
    household = await get_member_household(session, user.id, household_id)
    if household is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Household not found")
    return household


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
            User.status == UserStatus.active,
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


def _resolve_current_assignee(pool: list[User], current_assignee_id: int | None) -> User | None:
    """Validate an explicitly chosen current assignee against the pool (400 if not a
    member), or None when none was given (the caller then derives one from the strategy)."""
    if current_assignee_id is None:
        return None
    match = next((u for u in pool if u.id == current_assignee_id), None)
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The current assignee must be one of the chore's assignees",
        )
    return match


async def _completion_counts(session: SessionDep, chore_id: int) -> dict[int, int]:
    """Completions of this chore per crediting member (done occurrences grouped by
    completed_by_user_id). Used only by the `least_done` strategy."""
    rows = await session.execute(
        select(ChoreOccurrence.completed_by_user_id, func.count())
        .where(
            ChoreOccurrence.chore_id == chore_id,
            ChoreOccurrence.status == OccurrenceStatus.done,
        )
        .group_by(ChoreOccurrence.completed_by_user_id)
    )
    return {uid: count for uid, count in rows.all() if uid is not None}


async def _successor_assignee(
    session: SessionDep, chore: Chore, current_assignee_id: int | None, pool: list[User]
) -> User | None:
    """Who is on the hook for the occurrence that follows a completion. Holds the
    current assignee mid-turn; on a turn boundary the strategy picks the next person.
    Counts are read after the completion is flushed, so they include it (the
    post-completion snapshot least_done needs to actually rotate)."""
    if not pool:
        return None
    current = next((u for u in pool if u.id == current_assignee_id), None)
    done_count = (
        await session.scalar(
            select(func.count())
            .select_from(ChoreOccurrence)
            .where(
                ChoreOccurrence.chore_id == chore.id,
                ChoreOccurrence.status == OccurrenceStatus.done,
            )
        )
        or 0
    )
    if not should_reassign(done_count, chore.turn_length):
        return current
    counts = (
        await _completion_counts(session, chore.id)
        if chore.assignment_type == AssignmentType.least_done
        else {}
    )
    return next_assignee(chore.assignment_type, pool, current, counts)


async def _reconcile_open_occurrence(
    session: SessionDep, chore: Chore, payload: ChoreUpdate, pool: list[User]
) -> None:
    """Bring the chore's open occurrence in line with an edit.

    - No open occurrence (a completed one-off): revive it with a fresh open occurrence
      when the chore is now recurring, so a manual->recurring edit makes it due again;
      a still-manual completed one-off stays done.
    - An open, never-completed occurrence: keep its due date aligned to `start_date`
      (it is still the chore's first occurrence) and reconcile its assignee.
    - An open occurrence past at least one completion: its `scheduled_for` sits on the
      recurrence grid, so leave it; only reconcile the assignee.
    """
    occ = await _open_occurrence(session, chore.id)
    latest_done = (
        await session.execute(
            select(ChoreOccurrence)
            .where(
                ChoreOccurrence.chore_id == chore.id,
                ChoreOccurrence.status == OccurrenceStatus.done,
            )
            .order_by(ChoreOccurrence.scheduled_for.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if occ is None:
        if chore.repeats == RepeatPeriod.manual:
            return  # a completed one-off stays done
        scheduled = (
            next_occurrence_after(
                latest_done.scheduled_for, latest_done.completed_at, chore.repeats
            )
            if latest_done is not None
            else first_occurrence(payload.start_date)
        )
        if scheduled is None:
            return
        current = _resolve_current_assignee(pool, payload.current_assignee_id) or initial_assignee(
            chore.assignment_type, pool
        )
        session.add(
            ChoreOccurrence(
                chore_id=chore.id,
                scheduled_for=scheduled,
                assignee_id=current.id if current is not None else None,
                status=OccurrenceStatus.open,
            )
        )
        return

    # Reconcile the current assignee: honour an explicit choice, keep a still-valid
    # assignee, else recompute from the strategy.
    explicit = _resolve_current_assignee(pool, payload.current_assignee_id)
    if explicit is not None:
        occ.assignee_id = explicit.id
    elif occ.assignee_id is None or not any(a.id == occ.assignee_id for a in pool):
        nxt = initial_assignee(chore.assignment_type, pool)
        occ.assignee_id = nxt.id if nxt is not None else None
    # Before any completion the open occurrence is the first one, so its due date must
    # follow a start_date edit (mirrors the old never-completed next_due behaviour).
    if latest_done is None:
        occ.scheduled_for = first_occurrence(payload.start_date)


@router.post("", response_model=ChoreRead, status_code=status.HTTP_201_CREATED)
async def create_chore(payload: ChoreCreate, user: CurrentUser, session: SessionDep) -> Chore:
    household = await _resolve_household_or_404(session, user, payload.household_id)
    assignees = await _resolve_assignees(session, household, payload.assignee_ids)
    tags = await _resolve_tags(session, household, payload.tag_ids)
    chore = Chore(
        household_id=household.id,
        title=payload.title,
        description=payload.description,
        start_date=payload.start_date,
        repeats=payload.repeats,
        assignment_type=payload.assignment_type,
        turn_length=payload.turn_length,
        assignees=assignees,
        tags=tags,
    )
    session.add(chore)
    await session.flush()  # assign chore.id before creating its first occurrence
    # The initial current assignee: an explicit choice (validated), else derived from
    # the strategy (manual with several members has no auto-pick -> unassigned/shared).
    current = _resolve_current_assignee(assignees, payload.current_assignee_id)
    if current is None:
        current = initial_assignee(payload.assignment_type, assignees)
    session.add(
        ChoreOccurrence(
            chore_id=chore.id,
            scheduled_for=first_occurrence(payload.start_date),
            assignee_id=current.id if current is not None else None,
            status=OccurrenceStatus.open,
        )
    )
    await session.commit()
    return await _load_chore(session, chore.id)


@router.get("", response_model=Page[ChoreRead])
async def list_chores(
    user: CurrentUser,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: ChoreSortBy = "start_date",
    sort_dir: SortDir = "asc",
    household_id: Annotated[int | None, Query(ge=1)] = None,
) -> Page[ChoreRead]:
    # Scope to non-deleted chores in the user's active households; an optional
    # household_id narrows to one of them (a non-member id yields an empty page).
    filters = [Chore.deleted_at.is_(None), Chore.household_id.in_(member_household_ids(user.id))]
    if household_id is not None:
        filters.append(Chore.household_id == household_id)

    total = await session.scalar(select(func.count()).select_from(Chore).where(*filters)) or 0

    descending = sort_dir == "desc"
    order_by = [col.desc() if descending else col.asc() for col in CHORE_SORT_COLUMNS[sort_by]]
    order_by.append(Chore.id.desc() if descending else Chore.id.asc())  # stable tiebreaker

    result = await session.execute(
        select(Chore)
        .join(Household, Household.id == Chore.household_id)  # to-one: no row multiplication
        .options(
            selectinload(Chore.assignees),
            selectinload(Chore.tags),
            contains_eager(Chore.household),
        )
        .where(*filters)
        .order_by(*order_by)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    chores = list(result.scalars().all())
    await _attach_current_assignee(session, chores)
    items = [ChoreRead.model_validate(chore) for chore in chores]
    return Page[ChoreRead](items=items, total=total, page=page, page_size=page_size)


@router.get("/{chore_id}", response_model=ChoreRead)
async def get_chore(chore_id: int, user: CurrentUser, session: SessionDep) -> Chore:
    chore = await _get_user_chore_or_404(session, user, chore_id)
    await _attach_current_assignee(session, [chore])
    return chore


@router.patch("/{chore_id}", response_model=ChoreRead)
async def update_chore(
    chore_id: int, payload: ChoreUpdate, user: CurrentUser, session: SessionDep
) -> Chore:
    chore = await _get_user_chore_or_404(session, user, chore_id)
    # The household is fixed at creation; re-validate assignees/tags against it.
    assignees = await _resolve_assignees(session, chore.household, payload.assignee_ids)
    tags = await _resolve_tags(session, chore.household, payload.tag_ids)
    chore.title = payload.title
    chore.description = payload.description
    chore.start_date = payload.start_date
    chore.repeats = payload.repeats
    chore.assignment_type = payload.assignment_type
    chore.turn_length = payload.turn_length
    chore.assignees = assignees
    chore.tags = tags
    await _reconcile_open_occurrence(session, chore, payload, assignees)
    await session.commit()
    return await _load_chore(session, chore.id)


@router.delete("/{chore_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chore(chore_id: int, user: CurrentUser, session: SessionDep) -> None:
    chore = await _get_user_chore_or_404(session, user, chore_id)
    chore.deleted_at = datetime.now(UTC)
    await session.commit()


@router.post(
    "/{chore_id}/complete", response_model=CompletionRead, status_code=status.HTTP_201_CREATED
)
async def complete_chore(
    chore_id: int,
    user: CurrentUser,
    session: SessionDep,
    payload: CompleteChoreRequest | None = None,
) -> CompletionRead:
    """Mark a chore's current occurrence done. Any member of the chore's household
    may complete it. Flips the open occurrence to `done` (the history row) and, for a
    recurring chore, materialises the next open occurrence one interval on - reassigned
    to the next person when the turn ends (see _successor_assignee).

    By default the completion is credited to the caller. An optional
    `completed_by_user_id` credits it to another member so the History shows it under
    their name (used by the Home due view's credit dialog), but only if that member is
    one of the chore's assignees; the assignee pool is never modified."""
    chore = await _get_user_chore_or_404(session, user, chore_id)
    occ = await _open_occurrence(session, chore.id)
    if occ is None:
        # No open occurrence: a completed manual one-off has nothing left to do.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This chore has already been completed",
        )
    # Who the History credits. The caller may hand a completion to one of the chore's
    # assignees, but not to an arbitrary user (crediting yourself is always allowed,
    # e.g. an unassigned chore or "Done as me").
    completed_by_id = user.id
    if payload is not None and payload.completed_by_user_id is not None:
        completed_by_id = payload.completed_by_user_id
        if completed_by_id != user.id and not any(a.id == completed_by_id for a in chore.assignees):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A completion can only be credited to the current user or an assignee",
            )
    now = datetime.now(UTC)
    scheduled_for = occ.scheduled_for
    # Flip the current occurrence to done FIRST (it becomes the history row and frees
    # the one-open-per-chore slot), then materialise the successor - never the reverse,
    # or the two momentarily-open rows would trip the partial unique index.
    occ.status = OccurrenceStatus.done
    occ.title = chore.title
    occ.completed_by_user_id = completed_by_id
    occ.completed_at = now
    await session.flush()

    # Anchor the successor to the occurrence just cleared (skip-missed applied), so its
    # due date advances one interval on the grid rather than from the completion time.
    upcoming = next_occurrence_after(scheduled_for, now, chore.repeats)
    if upcoming is not None:
        next_person = await _successor_assignee(
            session, chore, occ.assignee_id, list(chore.assignees)
        )
        session.add(
            ChoreOccurrence(
                chore_id=chore.id,
                scheduled_for=upcoming,
                assignee_id=next_person.id if next_person is not None else None,
                status=OccurrenceStatus.open,
            )
        )
    completion_id = occ.id
    completion_title = occ.title
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent double-submit races to create the same successor occurrence (or
        # re-complete the same slot); the unique guards turn that into a 409, not a 500.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This chore has already been completed",
        ) from None

    days = days_until_due(upcoming, now) if upcoming is not None else None
    return CompletionRead(
        id=completion_id,
        chore_id=chore_id,
        title=completion_title,
        scheduled_for=scheduled_for,
        completed_by_user_id=completed_by_id,
        created_at=now,
        next_due=upcoming,
        days_until_due=days,
        status=due_status(days) if days is not None else None,
    )

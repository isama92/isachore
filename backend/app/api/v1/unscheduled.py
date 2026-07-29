from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep
from app.core.chores import days_since
from app.core.households import assignee_visibility, chore_scope
from app.models import Chore, ChoreOccurrence, OccurrenceStatus, RepeatPeriod
from app.schemas import UnscheduledChoreRead, UnscheduledRead
from app.schemas.chore import ChoreHouseholdRead
from app.schemas.household import HouseholdMemberRead

router = APIRouter()


async def _last_completions(session: SessionDep, chore_ids: list[int]) -> dict[int, datetime]:
    """The most recent completion time per chore, for the chores given. One grouped query
    rather than one per row, the same batching `_attach_current_assignee` does for the
    chores list. Chores never completed are simply absent from the mapping."""
    if not chore_ids:
        return {}
    rows = await session.execute(
        select(ChoreOccurrence.chore_id, func.max(ChoreOccurrence.completed_at))
        .where(
            ChoreOccurrence.chore_id.in_(chore_ids),
            ChoreOccurrence.status == OccurrenceStatus.done,
        )
        .group_by(ChoreOccurrence.chore_id)
    )
    # completed_at is nullable on the model, so a done row written without one (no production
    # path does) would yield a NULL max; drop those rather than report "never done" wrongly.
    return {chore_id: last for chore_id, last in rows.all() if last is not None}


@router.get("", response_model=UnscheduledRead)
async def get_unscheduled(
    user: CurrentUser,
    session: SessionDep,
    household_id: Annotated[int | None, Query(ge=1)] = None,
    # A repeatable query param (?assignee_id=1&assignee_id=2), same shape as the due view.
    assignee_id: Annotated[list[int] | None, Query()] = None,
) -> UnscheduledRead:
    """The unscheduled view: chores with no schedule, which you do whenever you feel like
    it, across the user's active households. They have no due date and are never overdue,
    so there is no progress and no ordering by urgency: the list is alphabetical, and each
    row reports how long since it was last done.

    Unlike the due view every chore here stays listed forever, because completing an
    unscheduled chore reopens it at once (see `core.chores.next_occurrence_after`). Filters
    match the due view: `household_id` narrows to one household, `assignee_id` (repeatable)
    keeps those members' chores plus unassigned/shared ones. Unpaginated, like the due view.
    """
    now = datetime.now(UTC)
    filters = [
        *chore_scope(user.id, household_id),
        Chore.repeats == RepeatPeriod.manual,
        ChoreOccurrence.status == OccurrenceStatus.open,
    ]
    assignee_clause = assignee_visibility(assignee_id)
    if assignee_clause is not None:
        filters.append(assignee_clause)

    result = await session.execute(
        select(ChoreOccurrence)
        .join(Chore, Chore.id == ChoreOccurrence.chore_id)
        .options(
            selectinload(ChoreOccurrence.assignee),
            selectinload(ChoreOccurrence.chore).selectinload(Chore.household),
        )
        .where(*filters)
        # Alphabetical, with the id as a stable tiebreaker for chores sharing a title.
        .order_by(Chore.title, Chore.id)
    )
    occurrences = result.scalars().all()

    last_done = await _last_completions(session, [occ.chore_id for occ in occurrences])

    def since(chore_id: int) -> int | None:
        last = last_done.get(chore_id)
        return days_since(last, now) if last is not None else None

    return UnscheduledRead(
        items=[
            UnscheduledChoreRead(
                id=occ.chore_id,
                title=occ.chore.title,
                days_since_last_completion=since(occ.chore_id),
                # Free: the query already selectinloads the whole Chore. See home.py.
                has_description=occ.chore.description is not None,
                household=ChoreHouseholdRead.model_validate(occ.chore.household),
                # Only the current assignee shows, as on the due view (the pool lives on
                # the chore).
                assignees=(
                    [HouseholdMemberRead.model_validate(occ.assignee)] if occ.assignee else []
                ),
            )
            for occ in occurrences
        ]
    )

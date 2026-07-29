from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep
from app.core.chores import days_until_due, due_status
from app.core.households import member_household_ids
from app.models import Chore, ChoreOccurrence, OccurrenceStatus, RepeatPeriod
from app.schemas import DueChoreRead, HomeRead, ProgressRead
from app.schemas.chore import ChoreHouseholdRead
from app.schemas.household import HouseholdMemberRead

router = APIRouter()


def chore_scope(user_id: int, household_id: int | None) -> list[ColumnElement[bool]]:
    """Chore-level scope shared by the two occurrence views (here and
    `api/v1/unscheduled.py`): live chores in the user's active households, optionally
    narrowed to one. A household the user cannot see yields an empty scope rather than a
    403, like the chores list. Neither caller wants the same repeat periods, so the
    `repeats` predicate is left to them."""
    scope = [
        Chore.deleted_at.is_(None),
        Chore.household_id.in_(member_household_ids(user_id)),
    ]
    if household_id is not None:
        scope.append(Chore.household_id == household_id)
    return scope


def assignee_visibility(assignee_id: list[int] | None) -> ColumnElement[bool] | None:
    """The selected members' occurrences, plus unassigned/shared ones (which belong to
    everyone), or None for no assignee filter at all. The current assignee alone decides
    visibility, so a rotating chore leaves your list the moment it hands off."""
    if not assignee_id:
        return None
    return or_(ChoreOccurrence.assignee_id.is_(None), ChoreOccurrence.assignee_id.in_(assignee_id))


@router.get("", response_model=HomeRead)
async def get_home(
    user: CurrentUser,
    session: SessionDep,
    household_id: Annotated[int | None, Query(ge=1)] = None,
    # A repeatable query param (?assignee_id=1&assignee_id=2). No ge constraint:
    # for a list param it would apply to the whole list, and a non-matching id
    # simply filters to nothing anyway.
    assignee_id: Annotated[list[int] | None, Query()] = None,
) -> HomeRead:
    """The due view: scheduled chores that are overdue, due today, or upcoming (no cut-off,
    so a chore due weeks out still shows), plus today's completion progress,
    across the user's active households. Unscheduled chores are not due dated and so
    never appear here; `api/v1/unscheduled.py` lists those.

    Filters (both optional): `household_id` narrows to one of the user's
    households; `assignee_id` (repeatable) keeps chores assigned to any of those
    members PLUS unassigned/shared chores (which belong to everyone). With no
    `assignee_id` the whole household is shown. The frontend seeds `assignee_id`
    with the current user, so the default view is "your chores + shared", and
    adding or clearing members widens it. Progress is computed over the same
    filtered scope. A household or member id the user can't see just yields an
    empty scope, like the chores list."""
    now = datetime.now(UTC)
    # UTC day bounds (not a `::date` cast, which depends on the session TimeZone).
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    tomorrow_start = today_start + timedelta(days=1)

    # Unscheduled chores are deliberately absent from both queries below: they carry no due
    # date, so they can be neither overdue nor due today, and counting them in today's
    # progress would move a denominator nothing on this page can ever satisfy. They have
    # their own view instead (api/v1/unscheduled.py).
    scope = [*chore_scope(user.id, household_id), Chore.repeats != RepeatPeriod.manual]
    assignee_clause = assignee_visibility(assignee_id)

    open_filters = [
        *scope,
        ChoreOccurrence.status == OccurrenceStatus.open,
    ]
    if assignee_clause is not None:
        open_filters.append(assignee_clause)

    result = await session.execute(
        select(ChoreOccurrence)
        .join(Chore, Chore.id == ChoreOccurrence.chore_id)
        .options(
            selectinload(ChoreOccurrence.assignee),
            selectinload(ChoreOccurrence.chore).selectinload(Chore.household),
        )
        .where(*open_filters)
    )
    occurrences = result.scalars().all()

    items: list[DueChoreRead] = []
    pending_ids: set[int] = set()  # overdue or due today, still not done
    for occ in occurrences:
        days = days_until_due(occ.scheduled_for, now)
        if days <= 0:
            pending_ids.add(occ.chore_id)
        items.append(
            DueChoreRead(
                id=occ.chore_id,
                title=occ.chore.title,
                repeats=occ.chore.repeats,
                repeat_interval=occ.chore.repeat_interval,
                weekdays=occ.chore.weekdays,
                next_due=occ.scheduled_for,
                days_until_due=days,
                status=due_status(days),
                household=ChoreHouseholdRead.model_validate(occ.chore.household),
                # Only the current assignee shows on Home (the pool lives on the chore).
                assignees=(
                    [HouseholdMemberRead.model_validate(occ.assignee)] if occ.assignee else []
                ),
            )
        )
    items.sort(key=lambda item: (item.next_due, item.id))  # most overdue first

    # Today's progress over the same scope: an occurrence completed today (whose slot
    # was due today or earlier) counts as done; overdue/due-today open ones are pending.
    done_filters = [
        *scope,
        ChoreOccurrence.status == OccurrenceStatus.done,
        ChoreOccurrence.completed_at >= today_start,
        ChoreOccurrence.completed_at < tomorrow_start,
        ChoreOccurrence.scheduled_for < tomorrow_start,
    ]
    if assignee_clause is not None:
        done_filters.append(assignee_clause)
    done_result = await session.execute(
        select(ChoreOccurrence.chore_id)
        .join(Chore, Chore.id == ChoreOccurrence.chore_id)
        .where(*done_filters)
        .distinct()
    )
    done_ids = set(done_result.scalars().all())

    progress = ProgressRead(done_today=len(done_ids), total_today=len(pending_ids | done_ids))
    return HomeRead(progress=progress, items=items)

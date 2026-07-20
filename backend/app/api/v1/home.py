from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep
from app.core.chores import days_until_due, due_status, next_due
from app.core.households import member_household_ids
from app.models import Chore, CompletedChore, User
from app.schemas import DueChoreRead, HomeRead, ProgressRead
from app.schemas.chore import ChoreHouseholdRead
from app.schemas.household import HouseholdMemberRead

router = APIRouter()

# Chores due within this many days ahead show on the Home due view.
DUE_SOON_DAYS = 7


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
    """The due view: chores that are overdue, due today, or due within the next
    week, plus today's completion progress, across the user's active households.

    Filters (both optional): `household_id` narrows to one of the user's
    households; `assignee_id` (repeatable) keeps chores assigned to any of those
    members PLUS unassigned/shared chores (which belong to everyone). With no
    `assignee_id` the whole household is shown. The frontend seeds `assignee_id`
    with the current user, so the default view is "your chores + shared", and
    adding or clearing members widens it. Progress is computed over the same
    filtered scope. A household or member id the user can't see just yields an
    empty scope, like the chores list."""
    now = datetime.now(UTC)

    # Scaling note: next_due is derived from start_date + repeats + schedule_anchor
    # (with month/year clamping), so it can't be expressed in SQL and the due-window
    # filter runs in Python below. This loads every in-scope chore per request -
    # O(chores in scope), regardless of how few are actually due. Fine for a
    # household-sized app; revisit (e.g. a stored/materialised next_due) if a
    # household ever holds a large number of chores.
    filters = [
        Chore.deleted_at.is_(None),
        Chore.household_id.in_(member_household_ids(user.id)),
    ]
    if household_id is not None:
        filters.append(Chore.household_id == household_id)
    if assignee_id:
        # The selected members' chores, plus unassigned/shared chores (everyone's).
        filters.append(or_(~Chore.assignees.any(), Chore.assignees.any(User.id.in_(assignee_id))))

    result = await session.execute(
        select(Chore)
        .options(selectinload(Chore.assignees), selectinload(Chore.household))
        .where(*filters)
    )
    chores = result.scalars().all()

    scoped_ids = {chore.id for chore in chores}
    items: list[DueChoreRead] = []
    pending_ids: set[int] = set()  # overdue or due today, still not done
    for chore in chores:
        due = next_due(chore)
        if due is None:  # a completed one-off has no next occurrence
            continue
        days = days_until_due(due, now)
        if days <= 0:
            pending_ids.add(chore.id)
        if days <= DUE_SOON_DAYS:
            items.append(
                DueChoreRead(
                    id=chore.id,
                    title=chore.title,
                    repeats=chore.repeats,
                    next_due=due,
                    days_until_due=days,
                    status=due_status(days),
                    household=ChoreHouseholdRead.model_validate(chore.household),
                    assignees=[HouseholdMemberRead.model_validate(a) for a in chore.assignees],
                )
            )
    items.sort(key=lambda item: (item.next_due, item.id))  # most overdue first

    # Today's progress over the filtered scope; completions by ANY member count.
    # UTC day bounds (not a `::date` cast, which depends on the session TimeZone).
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    tomorrow_start = today_start + timedelta(days=1)
    done_ids: set[int] = set()
    if scoped_ids:
        done_result = await session.execute(
            select(CompletedChore.chore_id)
            .where(
                CompletedChore.chore_id.in_(scoped_ids),
                CompletedChore.created_at >= today_start,
                CompletedChore.created_at < tomorrow_start,
                CompletedChore.scheduled_for < tomorrow_start,
            )
            .distinct()
        )
        done_ids = set(done_result.scalars().all())

    progress = ProgressRead(done_today=len(done_ids), total_today=len(pending_ids | done_ids))
    return HomeRead(progress=progress, items=items)

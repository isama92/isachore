from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep
from app.core import clock
from app.core.chores import days_until_due, due_status, local_day_bounds
from app.core.households import (
    assignee_visibility,
    chore_scope,
    household_zone,
    zones_in_scope,
)
from app.models import Chore, ChoreOccurrence, OccurrenceStatus, RepeatPeriod
from app.schemas import DueChoreRead, HomeRead, ProgressRead
from app.schemas.chore import ChoreHouseholdRead
from app.schemas.household import HouseholdMemberRead

router = APIRouter()


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
    now = clock.now()
    # Today starts at a different instant in each household, so there is no single day window
    # to filter by: the zones are collected here and the progress query below ORs one window
    # per zone. Nearly always an `or_` of one, since a user's households are nearly always in
    # the same place. See `local_day_bounds` for why this is Python rather than SQL.
    zones = await zones_in_scope(session, user.id, household_id)
    # Precomputed rather than derived inside the comprehension below, matching how stats.py
    # shapes the same thing: a one-element `for ... in [local_day_bounds(...)]` used as a `let`
    # reads as a mistake even when it is not.
    windows = {tz: local_day_bounds(now, tz) for tz in zones}

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
        # The household is already selectinloaded by the query above, so the zone costs no
        # extra query.
        days = days_until_due(occ.scheduled_for, now, household_zone(occ.chore.household.timezone))
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
                # No extra query: the chore is already selectinloaded. Not free of bytes,
                # though - that eager load pulls every column including description, so the
                # HTML still crosses from Postgres to the app even though it never reaches the
                # client. Fine at household scale; if it ever matters, select a labelled
                # `description IS NOT NULL` and defer the column (a bare defer() would turn
                # this attribute access into an async lazy load).
                #
                # NULL is the only "no description" (app/core/richtext.py collapses
                # visually-empty HTML), so this needs no emptiness check.
                has_description=occ.chore.description is not None,
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
    #
    # This is one of the two queries that deliberately does NOT exclude skipped occurrences
    # (see `ChoreOccurrence.skipped`). The bar answers "how much of today's list have you
    # got through", and a skipped chore is off the list: it was dealt with, decided about,
    # and is gone from the pending set either way. Statistics asks a different question -
    # how much work was done - and does filter them out, so the two disagree by design.
    #
    # One window per zone, ORed: "today" is a local question, so a household in Auckland is
    # judged against its own midnight rather than whichever household happened to be first.
    # The `false()` seed is what a user in no household collapses to - the right answer, since
    # the surrounding scope is empty too - and it is also what keeps this off SQLAlchemy's
    # deprecated argument-less `or_()`.
    done_filters = [
        *scope,
        ChoreOccurrence.status == OccurrenceStatus.done,
        or_(
            false(),
            *[
                and_(
                    Chore.household_id.in_(ids),
                    ChoreOccurrence.completed_at >= windows[tz][0],
                    ChoreOccurrence.completed_at < windows[tz][1],
                    ChoreOccurrence.scheduled_for < windows[tz][1],
                )
                for tz, ids in zones.items()
            ],
        ),
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

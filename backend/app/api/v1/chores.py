from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import contains_eager, selectinload

from app.api.deps import CurrentUser, SessionDep
from app.api.v1.households import SortDir
from app.core.assignment import initial_assignee, next_assignee, should_reassign
from app.core.chores import (
    RecurrenceRule,
    days_until_due,
    due_status,
    first_occurrence,
    next_occurrence_after,
    next_slot_after,
    snap_to_slot,
)
from app.core.households import (
    escape_like,
    get_member_household,
    member_household_ids,
    require_role,
)
from app.models import (
    AssignmentType,
    Chore,
    ChoreOccurrence,
    Household,
    HouseholdRole,
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
    unassigned/shared (every live chore has an open occurrence)."""
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


async def _managed_chore_or_error(session: SessionDep, user: User, chore_id: int) -> Chore:
    """A chore the caller may *change*: one they can see (404 otherwise) in a household
    where they are an organiser (403 otherwise).

    Reading a chore deliberately has no such gate (`get_chore` keeps
    `_get_user_chore_or_404`): the description dialog on Home and Unscheduled fetches the
    full chore, and helpers use it. Only writes need the role."""
    chore = await _get_user_chore_or_404(session, user, chore_id)
    await require_role(session, chore.household_id, user.id, HouseholdRole.organiser)
    return chore


async def _resolve_household_or_404(
    session: SessionDep, user: User, household_id: int
) -> Household:
    """The household a new chore is being created in. Non-organisers get a 403 rather
    than the 404 a non-member gets, since they can see the household perfectly well."""
    household = await get_member_household(session, user.id, household_id)
    if household is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Household not found")
    await require_role(session, household.id, user.id, HouseholdRole.organiser)
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


def _rule(chore: Chore) -> RecurrenceRule:
    """The chore's recurrence rule, as the pure `core.chores` helpers want it."""
    return RecurrenceRule.of(chore.repeats, chore.repeat_interval, chore.weekdays)


def _initial_slot(start_date: date | None, rule: RecurrenceRule, now: datetime) -> datetime:
    """Where a chore's first open occurrence sits. A scheduled chore opens on its start
    date; an unscheduled one has no start date and opens now, reading as "available since"
    rather than a deadline."""
    return first_occurrence(start_date, rule) if start_date is not None else now


async def _free_slot_from(
    session: SessionDep, chore_id: int, candidate: datetime, rule: RecurrenceRule
) -> datetime:
    """`candidate`, advanced along the grid past every slot this chore has already completed.

    Re-dating a chore onto a grid it has history on can land exactly on one of its `done`
    rows, and `uq_occurrence_chore_scheduled` is per (chore, scheduled_for): the commit would
    fail and `update_chore` would surface a 409 that retrying could never get past, because
    the same edit recomputes the same occupied slot every time. It used to be impossible - an
    open row's slot was always later than every done row's - but unscheduled chores broke
    that: one anchors its successors at completion timestamps, so a chore that was unscheduled
    for a while has done rows on both sides of its open one.

    Walking forward applies the same rule `advance_anchor` already does: a slot the chore has
    been completed for is not a slot it can be due for again. The rule always has an interval
    to step, since a candidate only exists when there is a start date (never `manual`), and it
    terminates because every step strictly advances while the done set is finite.
    """
    taken = set(
        (
            await session.execute(
                select(ChoreOccurrence.scheduled_for).where(
                    ChoreOccurrence.chore_id == chore_id,
                    ChoreOccurrence.status == OccurrenceStatus.done,
                    ChoreOccurrence.scheduled_for >= candidate,
                )
            )
        )
        .scalars()
        .all()
    )
    slot = candidate
    while slot in taken:
        slot = next_slot_after(slot, rule)
    return slot


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
    session: SessionDep,
    chore: Chore,
    payload: ChoreUpdate,
    pool: list[User],
    *,
    was_unscheduled: bool,
) -> None:
    """Bring the chore's open occurrence in line with an edit. `was_unscheduled` is the
    chore's period *before* the edit, which `update_chore` has already overwritten by the
    time this runs but which decides whether the open slot sits on a grid at all.

    - No open occurrence: revive it. Only reachable for a chore left terminated by the
      one-off semantics that predated unscheduled chores (the migration clears those), or
      by a concurrent undo, since completing a chore now always reopens it.
    - An open occurrence with no grid behind it - the chore's first, or one belonging to a
      chore that was unscheduled until this edit: (re-)seed it from `start_date`.
    - An open occurrence past at least one completion on a grid: its `scheduled_for` sits on
      the grid the chore had when the row was written, and an edit can redefine that grid, so
      snap it onto the new one.

    Either way the assignee is reconciled. An unscheduled chore has no start date, so its
    slot always stands.
    """
    rule = _rule(chore)
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
        scheduled = (
            # `completed_at` is nullable on the model; no production path writes a done row
            # without it, so fall back to the slot rather than carrying an Optional through
            # the pure helpers.
            next_occurrence_after(
                latest_done.scheduled_for,
                latest_done.completed_at or latest_done.scheduled_for,
                rule,
            )
            if latest_done is not None
            else _initial_slot(payload.start_date, rule, datetime.now(UTC))
        )
        # Same shape as create_chore's version below, deliberately: the ternary this replaces
        # relied on `or` binding tighter than the conditional expression, which parsed correctly
        # but read as though the `or` might attach to the whole else branch.
        current = None
        if not payload.clear_current_assignee:
            current = _resolve_current_assignee(
                pool, payload.current_assignee_id
            ) or initial_assignee(chore.assignment_type, pool)
        session.add(
            ChoreOccurrence(
                chore_id=chore.id,
                scheduled_for=scheduled,
                assignee_id=current.id if current is not None else None,
                status=OccurrenceStatus.open,
            )
        )
        return

    # Reconcile the current assignee: clear it if asked, else honour an explicit choice, keep a
    # still-valid assignee, else recompute from the strategy.
    #
    # The clear branch has to come first AND stop here, because "unassigned" is a destination,
    # not an absence: falling through to the elif below would immediately re-derive somebody
    # from the strategy and undo it. For the auto strategies this lasts until the next
    # completion, like any other override (`_successor_assignee` re-derives); for `manual` it
    # stands until someone sets an assignee again.
    explicit = _resolve_current_assignee(pool, payload.current_assignee_id)
    if payload.clear_current_assignee:
        occ.assignee_id = None
    elif explicit is not None:
        occ.assignee_id = explicit.id
    elif occ.assignee_id is None or not any(a.id == occ.assignee_id for a in pool):
        nxt = initial_assignee(chore.assignment_type, pool)
        occ.assignee_id = nxt.id if nxt is not None else None
    # No start date means unscheduled: there is nothing for the slot to follow and no grid
    # to snap it to, and the slot only records when the chore became available, so it stands
    # whatever else the edit changed.
    if payload.start_date is not None:
        candidate = (
            # Before any completion the open occurrence is the first one, so its due date must
            # follow a start_date edit (mirrors the old never-completed next_due behaviour).
            # `was_unscheduled` takes the same branch even with completions behind it, because
            # an unscheduled chore's slot is its last completion moment ("available since"),
            # not a grid position: snapping that would hand a non-deadline straight to the due
            # machinery and land a chore the user just dated "today" weeks overdue.
            first_occurrence(payload.start_date, rule)
            if latest_done is None or was_unscheduled
            # Otherwise the row sits on the grid the chore had when it was written, which this
            # edit may have redefined. `snap_to_slot` is idempotent and moves it by days rather
            # than weeks (at most six, never backwards), so pinning weekdays re-dates the chore
            # without spending a whole cycle. Note a chore overdue by less than that can land
            # in the future and leave the overdue bucket - reasonable, since the edit just
            # declared which weekdays it happens on. Only pinning moves anything: every other
            # rule accepts any datetime, because its phase lives in the occurrence chain.
            else snap_to_slot(occ.scheduled_for, rule)
        )
        # Both candidates can land on a slot this chore has already completed, which
        # `_free_slot_from` is what keeps off a `done` row - see its docstring for why neither
        # is safe to assign blind.
        occ.scheduled_for = await _free_slot_from(session, chore.id, candidate, rule)


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
        repeat_interval=payload.repeat_interval,
        weekdays=payload.weekdays,
        assignees=assignees,
        tags=tags,
    )
    session.add(chore)
    await session.flush()  # assign chore.id before creating its first occurrence
    # The initial current assignee: unassigned if asked for, else an explicit choice
    # (validated), else derived from the strategy (manual with several members has no
    # auto-pick -> unassigned/shared anyway).
    current = None
    if not payload.clear_current_assignee:
        current = _resolve_current_assignee(assignees, payload.current_assignee_id)
        if current is None:
            current = initial_assignee(payload.assignment_type, assignees)
    session.add(
        ChoreOccurrence(
            chore_id=chore.id,
            scheduled_for=_initial_slot(payload.start_date, _rule(chore), datetime.now(UTC)),
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
    title: Annotated[str | None, Query(max_length=255)] = None,
) -> Page[ChoreRead]:
    # This is the chores *management* list, so it is scoped to non-deleted chores in the
    # active households where the caller is an organiser - the ones they can actually act
    # on. A household they are only a deputy or helper in yields nothing here while its
    # chores stay fully visible on Home and Unscheduled, which is the intent: less data
    # rather than a 403, since the list spans every household at once. An optional
    # household_id narrows further (an id they cannot manage yields an empty page), and an
    # optional title does a case-insensitive substring match.
    filters = [
        Chore.deleted_at.is_(None),
        Chore.household_id.in_(member_household_ids(user.id, HouseholdRole.organiser)),
    ]
    if household_id is not None:
        filters.append(Chore.household_id == household_id)
    if title and title.strip():
        filters.append(Chore.title.ilike(f"%{escape_like(title.strip())}%"))

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
    chore = await _managed_chore_or_error(session, user, chore_id)
    # The household is fixed at creation; re-validate assignees/tags against it.
    assignees = await _resolve_assignees(session, chore.household, payload.assignee_ids)
    tags = await _resolve_tags(session, chore.household, payload.tag_ids)
    # Read before the assignments below overwrite it: whether the open occurrence's slot sits
    # on a recurrence grid depends on the period the chore had, not the one it is getting.
    was_unscheduled = chore.repeats == RepeatPeriod.manual
    chore.title = payload.title
    chore.description = payload.description
    chore.start_date = payload.start_date
    chore.repeats = payload.repeats
    chore.assignment_type = payload.assignment_type
    chore.turn_length = payload.turn_length
    chore.repeat_interval = payload.repeat_interval
    chore.weekdays = payload.weekdays
    chore.assignees = assignees
    chore.tags = tags
    # Must run after the recurrence fields are assigned: it builds the rule from the chore.
    await _reconcile_open_occurrence(
        session, chore, payload, assignees, was_unscheduled=was_unscheduled
    )
    try:
        await session.commit()
    except IntegrityError:
        # Reconcile computes an occurrence slot, so it can collide with a slot a concurrent
        # POST /complete just wrote. This chore's own `done` rows are already accounted for
        # (`_free_slot_from` walks past them), so what is left is a genuine race, which a
        # retry can clear - unlike a self-collision, which would 409 forever.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This chore changed while you were editing it. Please try again.",
        ) from None
    return await _load_chore(session, chore.id)


@router.delete("/{chore_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chore(chore_id: int, user: CurrentUser, session: SessionDep) -> None:
    chore = await _managed_chore_or_error(session, user, chore_id)
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
    may complete it. Flips the open occurrence to `done` (the history row) and materialises
    the next open occurrence - one interval on for a recurring chore, at the completion
    moment for an unscheduled one, reassigned to the next person when the turn ends (see
    _successor_assignee). Every chore therefore stays completable, over and over.

    By default the completion is credited to the caller. An optional
    `completed_by_user_id` credits it to another member so the History shows it under
    their name (used by the Home due view's credit dialog), but only if that member is
    one of the chore's assignees; the assignee pool is never modified."""
    chore = await _get_user_chore_or_404(session, user, chore_id)
    occ = await _open_occurrence(session, chore.id)
    if occ is None:
        # Nothing open to complete. Not reachable by simply completing twice (the successor
        # below is unconditional), but a concurrent undo can clear the slot mid-request, and
        # a chore predating the unscheduled migration could still be sitting terminated.
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
    # An unscheduled chore has no grid and reopens at `now` instead.
    upcoming = next_occurrence_after(scheduled_for, now, _rule(chore))
    next_person = await _successor_assignee(session, chore, occ.assignee_id, list(chore.assignees))
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

    days = days_until_due(upcoming, now)
    return CompletionRead(
        id=completion_id,
        chore_id=chore_id,
        title=completion_title,
        scheduled_for=scheduled_for,
        completed_by_user_id=completed_by_id,
        created_at=now,
        next_due=upcoming,
        days_until_due=days,
        status=due_status(days),
    )

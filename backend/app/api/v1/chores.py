from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import contains_eager, defer, selectinload

from app.api.deps import CurrentUser, Impersonator, SessionDep
from app.api.v1.households import SortDir
from app.core import clock
from app.core.assignment import initial_assignee, next_assignee, should_reassign
from app.core.chores import (
    days_until_due,
    due_status,
    end_of_local_day,
    first_occurrence,
    next_occurrence_after,
    snap_to_slot,
)
from app.core.household_log import changed_chore_fields, record_log_entry, snapshot_chore
from app.core.households import (
    escape_like,
    get_member_household,
    household_zone,
    member_household_ids,
    require_role,
)
from app.core.occurrences import free_slot_from, initial_slot, rule_for, zone_for
from app.models import (
    AssignmentType,
    Chore,
    ChoreOccurrence,
    Household,
    HouseholdLogAction,
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
    ChoreListRead,
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


async def _completion_tally(session: SessionDep, chore_id: int) -> tuple[int, dict[int, int]]:
    """Completions of this chore: how many there have been, and how they split across the
    crediting members (done occurrences grouped by `completed_by_user_id`). One GROUP BY
    serves both, because `_successor_assignee` wants the total for the turn and the split for
    `least_done`, over the same rows with the same predicate.

    **The total is NOT `sum(counts.values())`**, which is why they are returned as a pair
    rather than derived from one another: `completed_by_user_id` is `ON DELETE SET NULL`, so a
    hard-deleted user leaves done rows crediting nobody. Those still spent a turn, so the total
    keeps them; the split drops them, having no one to credit.

    Skipped occurrences are excluded from both: this is a fairness tally, so counting them
    would make skipping a chore a way to climb the ranking without doing it, and they do not
    spend a turn either (see `_retained_assignee`)."""
    rows = (
        await session.execute(
            select(ChoreOccurrence.completed_by_user_id, func.count())
            .where(
                ChoreOccurrence.chore_id == chore_id,
                ChoreOccurrence.status == OccurrenceStatus.done,
                ChoreOccurrence.skipped.is_(False),
            )
            .group_by(ChoreOccurrence.completed_by_user_id)
        )
    ).all()
    return sum(count for _, count in rows), {uid: count for uid, count in rows if uid is not None}


async def _strategy_pick(session: SessionDep, chore: Chore, pool: list[User]) -> User | None:
    """`initial_assignee` with the tally `least_done` needs. Five handler-side paths derive an
    assignee from scratch and all of them come through here: `create_chore`, both branches of
    `_reconcile_open_occurrence`, and the stale-assignee case of both `_retained_assignee` and
    `_successor_assignee`. So no handler reaches `initial_assignee` any other way, and none can
    quietly fall back to ranking alphabetically. (`next_assignee` also calls it, for a current
    outside the pool - that one is pure and passes its own `counts`, so it cannot route here.)

    Most of those sit on a chore with history; `create_chore` and a revive with no closure
    behind it do not, and for them the query returns `{}` and the answer is the alphabetical
    one either way. That is why it is safe to funnel all five rather than special-casing the
    empty ones, and the gate below is about the *cost*, not the answer: no other strategy reads
    `counts` at all, and `initial_assignee` returns before consulting them for a pool of fewer
    than two, so in both cases the query could not change anything.

    Note `chore.assignment_type` is read live, which in the `update_chore` path means the
    *new* strategy: that handler assigns the payload onto the chore before reconciling, the
    same ordering `was_unscheduled` exists to work around. Intended here - a chore switched to
    `least_done` should be filled from the tally at once - but it is a second dependency on
    that ordering, so moving the reconcile call above the assignments would silently gate on
    the old strategy."""
    counts = (
        (await _completion_tally(session, chore.id))[1]
        if chore.assignment_type == AssignmentType.least_done and len(pool) > 1
        else {}
    )
    return initial_assignee(chore.assignment_type, pool, counts=counts)


async def _successor_assignee(
    session: SessionDep, chore: Chore, current_assignee_id: int | None, pool: list[User]
) -> User | None:
    """Who is on the hook for the occurrence that follows a completion. Holds the current
    assignee mid-turn (unless the pool no longer holds them, see below); on a turn boundary the
    strategy picks the next person. One tally read serves both halves of the ordinary path - the
    total decides whether the turn is up, the split feeds `least_done` - and it happens after
    the completion is flushed, so it includes it (the post-completion snapshot least_done needs:
    a tally one short reads as a strict minimum rather than the tie it really is, and whoever
    just finished would keep the chore for another turn). The mid-turn stale branch below is the
    exception, paying for a second identical read inside `_strategy_pick`: keeping one funnel to
    `initial_assignee` is worth more than a query on a path that needs an undo to reach.

    Skipped occurrences do not count towards the turn, because a skip does not hand the
    chore on (see `_retained_assignee`): counting them would spend someone's turn on work
    nobody did, so a `turn_length` of 3 could hand over after one real completion."""
    if not pool:
        return None
    current = next((u for u in pool if u.id == current_assignee_id), None)
    done_count, counts = await _completion_tally(session, chore.id)
    if not should_reassign(done_count, chore.turn_length):
        # Mid-turn, so the current assignee keeps it - but `current` is None in two ways that
        # are not the same thing, exactly as on the skip path. A deliberately unassigned row
        # (`clear_current_assignee`) is an answer to respect, and a clear is *meant* to outlive
        # completions up to the next turn boundary. A row naming somebody the pool no longer
        # holds is a gap, and standing still would leave the chore unassigned until that
        # boundary - which for a long turn is a chore nobody is on with no edit to blame.
        if current_assignee_id is not None and current is None:
            return await _strategy_pick(session, chore, pool)
        return current
    return next_assignee(chore.assignment_type, pool, current, counts)


async def _retained_assignee(
    session: SessionDep, chore: Chore, current_assignee_id: int | None, pool: list[User]
) -> User | None:
    """Who is on the hook for the occurrence that follows a SKIP: the same person, because
    skipping does not hand the chore on. Whoever chose not to do it this time is still up
    next, whatever the strategy says - which is what stops a skip being the cheap way to
    move work onto a housemate.

    **An unassigned occurrence stays unassigned**, which is the same rule applied honestly:
    NULL here means the chore is the household's and nobody in particular is up (see
    `clear_current_assignee`), so there is no turn to keep, and deriving somebody from the
    strategy would both invent a turn and silently undo a deliberate hand-back. This is where
    skipping parts company with completing: a clear survives completions only up to the next
    turn *boundary*, since `_successor_assignee` returns the (absent) current assignee while
    `should_reassign` is false and re-derives once it is - so with `turn_length=3` a clear
    outlives two completions and dies on the third. A skip is never that boundary.

    The strategy fallback is for the other case only, where the row names somebody the pool no
    longer contains: standing still would leave the chore on a person who cannot do it. Note
    this is deliberately NOT the same rule as `_reconcile_open_occurrence`'s, which recomputes
    for an unassigned row as well as a stale one - that is an edit reconciling the whole chore,
    where "no assignee" is a gap to fill, while here it is an answer to respect. The two agree
    on the stale case and differ on the empty one, and the difference is the point of this
    function. **Every way out of a closure now agrees on the stale case**: this one, and both
    branches of `_successor_assignee` - mid-turn through `_strategy_pick` like this one, at a
    turn boundary through `next_assignee`'s `_in_pool` check instead. What keeps the first two
    answering alike is that they share `_strategy_pick`: give one the completion tally and not
    the other and they would diverge for `least_done` alone.

    Counting is what the session is for, and only on that fallback: it stays in the `else`
    position below so an ordinary skip - the overwhelmingly common path, where the assignee is
    still in the pool - runs no extra query at all. The tally itself is honest for free, since
    `_close_occurrence` has already flushed this closure but `_completion_tally` filters
    skipped rows out, so a skip cannot pad the skipper's own standing."""
    if not pool or current_assignee_id is None:
        return None
    current = next((u for u in pool if u.id == current_assignee_id), None)
    return current if current is not None else await _strategy_pick(session, chore, pool)


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
    rule = rule_for(chore)
    tz = zone_for(chore)
    occ = await _open_occurrence(session, chore.id)
    # Structural, so skipped rows count here (see `ChoreOccurrence.skipped`): this asks where
    # the chain has got to, not what was achieved. Filtering them would pick an earlier closure
    # and, on the revive path below, seed a slot a skipped row already holds - and that path
    # inserts directly rather than going through `free_slot_from`, so nothing would catch it.
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
                tz,
            )
            if latest_done is not None
            else initial_slot(payload.start_date, rule, clock.now(), tz)
        )
        # Same shape as create_chore's version below, deliberately: the ternary this replaces
        # relied on `or` binding tighter than the conditional expression, which parsed correctly
        # but read as though the `or` might attach to the whole else branch. The strategy
        # fallback is the one thing that differs, and only because this chore has history for
        # `least_done` to rank on where a brand-new one has none.
        current = None
        if not payload.clear_current_assignee:
            current = _resolve_current_assignee(pool, payload.current_assignee_id)
            if current is None:
                current = await _strategy_pick(session, chore, pool)
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
        nxt = await _strategy_pick(session, chore, pool)
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
            first_occurrence(payload.start_date, rule, tz)
            if latest_done is None or was_unscheduled
            # Otherwise the row sits on the grid the chore had when it was written, which this
            # edit may have redefined. `snap_to_slot` is idempotent and moves it by days rather
            # than weeks (at most six, never backwards), so pinning weekdays re-dates the chore
            # without spending a whole cycle. Note a chore overdue by less than that can land
            # in the future and leave the overdue bucket - reasonable, since the edit just
            # declared which weekdays it happens on. Only pinning moves anything: every other
            # rule accepts any datetime, because its phase lives in the occurrence chain.
            else snap_to_slot(occ.scheduled_for, rule, tz)
        )
        # Both candidates can land on a slot this chore has already completed, which
        # `free_slot_from` is what keeps off a `done` row - see its docstring for why neither
        # is safe to assign blind.
        occ.scheduled_for = await free_slot_from(session, chore.id, candidate, rule, tz)


@router.post("", response_model=ChoreRead, status_code=status.HTTP_201_CREATED)
async def create_chore(
    payload: ChoreCreate, user: CurrentUser, session: SessionDep, impersonator: Impersonator
) -> Chore:
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
    # auto-pick -> unassigned/shared anyway). Through `_strategy_pick` like every other
    # derivation, even though a chore flushed moments ago has no completions for the tally to
    # find: keeping the one funnel means there is no second path to `initial_assignee` to
    # remember, and nothing here rests on "this chore cannot have history yet".
    current = None
    if not payload.clear_current_assignee:
        current = _resolve_current_assignee(assignees, payload.current_assignee_id)
        if current is None:
            current = await _strategy_pick(session, chore, assignees)
    session.add(
        ChoreOccurrence(
            chore_id=chore.id,
            scheduled_for=initial_slot(
                payload.start_date,
                rule_for(chore),
                clock.now(),
                household_zone(household.timezone),
            ),
            assignee_id=current.id if current is not None else None,
            status=OccurrenceStatus.open,
        )
    )
    # Staged in this transaction, so the log entry lands exactly when the chore does.
    await record_log_entry(
        session,
        action=HouseholdLogAction.chore_created,
        household_id=household.id,
        actor_id=user.id,
        chore_id=chore.id,
        chore_title=chore.title,
        impersonator_id=impersonator.id if impersonator else None,
    )
    await session.commit()
    return await _load_chore(session, chore.id)


@router.get("", response_model=Page[ChoreListRead])
async def list_chores(
    user: CurrentUser,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: ChoreSortBy = "start_date",
    sort_dir: SortDir = "asc",
    household_id: Annotated[int | None, Query(ge=1)] = None,
    title: Annotated[str | None, Query(max_length=255)] = None,
) -> Page[ChoreListRead]:
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

    # The description is answered as a labelled boolean and the column itself deferred, so
    # the HTML never leaves Postgres - not merely "is left off the wire". At the page cap
    # that is 100 x MAX_RICH_TEXT_LENGTH of markup not read, not serialised and not sent,
    # for a table that never renders it. `raiseload` makes a future
    # `chore.description` here fail with a clear error rather than the MissingGreenlet a
    # bare defer() turns an attribute access into under asyncpg.
    result = await session.execute(
        select(Chore, Chore.description.is_not(None).label("has_description"))
        .join(Household, Household.id == Chore.household_id)  # to-one: no row multiplication
        .options(
            selectinload(Chore.assignees),
            selectinload(Chore.tags),
            contains_eager(Chore.household),
            defer(Chore.description, raiseload=True),
        )
        .where(*filters)
        .order_by(*order_by)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    chores = []
    for chore, has_description in result.all():
        # A transient attribute the schema reads, the same trick _attach_current_assignee
        # uses for current_assignee.
        chore.has_description = has_description
        chores.append(chore)
    await _attach_current_assignee(session, chores)
    items = [ChoreListRead.model_validate(chore) for chore in chores]
    return Page[ChoreListRead](items=items, total=total, page=page, page_size=page_size)


@router.get("/{chore_id}", response_model=ChoreRead)
async def get_chore(chore_id: int, user: CurrentUser, session: SessionDep) -> Chore:
    chore = await _get_user_chore_or_404(session, user, chore_id)
    await _attach_current_assignee(session, [chore])
    return chore


@router.patch("/{chore_id}", response_model=ChoreRead)
async def update_chore(
    chore_id: int,
    payload: ChoreUpdate,
    user: CurrentUser,
    session: SessionDep,
    impersonator: Impersonator,
) -> Chore:
    chore = await _managed_chore_or_error(session, user, chore_id)
    # The household is fixed at creation; re-validate assignees/tags against it.
    assignees = await _resolve_assignees(session, chore.household, payload.assignee_ids)
    tags = await _resolve_tags(session, chore.household, payload.tag_ids)
    # Read before the assignments below overwrite it: whether the open occurrence's slot sits
    # on a recurrence grid depends on the period the chore had, not the one it is getting.
    was_unscheduled = chore.repeats == RepeatPeriod.manual
    # Same reason, for the log: what the chore looked like before this edit. Diffed against a
    # second snapshot of the same object below rather than against the payload, so the
    # assignments right here stay the only place that maps one onto the other.
    before = snapshot_chore(chore)
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
    changed = changed_chore_fields(before, snapshot_chore(chore))
    # Must run after the recurrence fields are assigned: it builds the rule from the chore.
    await _reconcile_open_occurrence(
        session, chore, payload, assignees, was_unscheduled=was_unscheduled
    )
    # Nothing moved, nothing to say: a resubmitted form is not an event. Staged BEFORE the
    # try, which is what makes the 409 path right for free - the rollback expunges this too,
    # so a failed edit leaves no entry and the retry writes exactly one.
    if changed:
        await record_log_entry(
            session,
            action=HouseholdLogAction.chore_updated,
            household_id=chore.household_id,
            actor_id=user.id,
            chore_id=chore.id,
            chore_title=chore.title,
            changed_fields=changed,
            impersonator_id=impersonator.id if impersonator else None,
        )
    try:
        await session.commit()
    except IntegrityError:
        # Reconcile computes an occurrence slot, so it can collide with a slot a concurrent
        # POST /complete just wrote. This chore's own `done` rows are already accounted for
        # (`free_slot_from` walks past them), so what is left is a genuine race, which a
        # retry can clear - unlike a self-collision, which would 409 forever.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This chore changed while you were editing it. Please try again.",
        ) from None
    return await _load_chore(session, chore.id)


@router.delete("/{chore_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chore(
    chore_id: int, user: CurrentUser, session: SessionDep, impersonator: Impersonator
) -> None:
    chore = await _managed_chore_or_error(session, user, chore_id)
    chore.deleted_at = clock.now()
    # The title as it stood at deletion: the chore row survives the soft delete, but the log
    # must keep reading correctly even if a later hard delete ever takes it.
    await record_log_entry(
        session,
        action=HouseholdLogAction.chore_deleted,
        household_id=chore.household_id,
        actor_id=user.id,
        chore_id=chore.id,
        chore_title=chore.title,
        impersonator_id=impersonator.id if impersonator else None,
    )
    await session.commit()


async def _close_occurrence(
    session: SessionDep,
    chore: Chore,
    occ: ChoreOccurrence,
    *,
    closed_by_id: int,
    skipped: bool,
    backdate: bool,
    conflict_detail: str,
) -> CompletionRead:
    """Close a chore's open occurrence and materialise its successor. Shared by completing
    and skipping, which differ only in `skipped` and in who ends up on the hook next, so the
    ordering below and the IntegrityError mapping are written once rather than twice.

    The successor's assignee is the one real behavioural fork: a completion hands the chore
    on when the turn ends (`_successor_assignee`), a skip keeps it where it is
    (`_retained_assignee`).

    **`backdate` splits the one `now` this used to have into two, and which value goes where
    is not interchangeable.** It dates the closure at the end of the occurrence's own local
    day instead of at the moment the button was pressed, for the chore somebody did and
    forgot to tick. Three consumers take that chosen instant - the stamped column, the
    successor derivation, and the echoed `created_at`, which in this API means the completion
    timestamp (`COMPLETION_SORT_COLUMNS["created_at"]` maps to `completed_at`). The fourth,
    `days_until_due` on the way out, must keep the *real* `now`: `GET /home` computes the
    same number from `clock.now()`, so a backdated one would have this 201 report "due in a
    day" for a successor that the very next page load calls overdue, in the same second.

    **The two values this closure is computed from are re-read under a row lock first**, and the
    order matters. `occ` and `chore` arrive from plain selects taken before this was called, so
    without the lock a concurrent `PATCH /households/{id}` changing the zone could commit in
    between - `reanchor_open_occurrences` holds `FOR UPDATE` on this very row, but that only
    delays *this* transaction's write, it does not invalidate the read it already took, and
    nothing carries a `version_id_col` to notice. The closure would then be computed from a slot
    and a zone that no longer belong together, silently:

      - the successor gets anchored on the old zone's grid and **stays** there, since every
        later completion walks from that anchor (measured 11 hours off for an
        Europe/Amsterdam to Pacific/Niue move);
      - and `completed_timezone` gets stamped with the old zone onto a row whose `scheduled_for`
        the re-anchor just moved to the new zone's midnight - mismatched operands for
        `days_late`, which is the one thing that column exists to prevent. Traced: 1 day late
        reported where the answer is 0.

    Neither raises `IntegrityError`, so nothing downstream catches it.

    Taking the lock before reading closes both interleavings. If the re-anchor got there first,
    this blocks and then re-reads the slot it wrote, and the zone select that follows sees the
    committed value (READ COMMITTED, fresh statement) - a consistent pair. If this got there
    first, the re-anchor blocks instead, this finishes on the old pair (also consistent, since
    nothing has changed yet), and once it commits the re-anchor's `status == open` predicate
    re-evaluates and skips the row, which is now `done`. It also covers the successor insert
    below, because nothing can reach that insert without holding this lock first.

    The residual is `undo_completion` reopening a row after the re-anchor's select has run,
    which leaves that row on the old grid until the next chore edit re-seeds it through
    `_reconcile_open_occurrence`. Narrower again, and self-healing, so it is documented rather
    than locked.
    """
    # `SELECT ... FOR UPDATE` on this one row, which is the row a completion already contends on -
    # not a household-wide advisory lock, which would serialise housemates completing different
    # chores.
    await session.refresh(occ, with_for_update=True)
    now = clock.now()
    # Read after the lock, never from `chore.household` - that was loaded before it.
    tz = household_zone(
        await session.scalar(select(Household.timezone).where(Household.id == chore.household_id))
        or "UTC"
    )
    scheduled_for = occ.scheduled_for
    # Computed here rather than any earlier because both operands are post-lock reads: the
    # slot above and the zone before it. Clamped to `now`, which is what makes the flag
    # self-limiting instead of needing an overdue check - for a chore due today or completed
    # early the end of its due day is still ahead, so the answer is `now`, which is on time
    # anyway. A caller that mis-decides therefore cannot date a completion into the future.
    completed_at = min(end_of_local_day(scheduled_for, tz), now) if backdate else now
    # Flip the current occurrence to done FIRST (it becomes the history row and frees
    # the one-open-per-chore slot), then materialise the successor - never the reverse,
    # or the two momentarily-open rows would trip the partial unique index.
    occ.status = OccurrenceStatus.done
    occ.skipped = skipped
    occ.title = chore.title
    occ.completed_by_user_id = closed_by_id
    occ.completed_at = completed_at
    # Snapshotted alongside `title`, and for the same reason: both are facts about this closure
    # that a later change to the chore or the household would otherwise rewrite. It is also the
    # same `tz` the backdate above was built from, which is what makes a backdated closure read
    # as `days_late == 0` by construction rather than by luck: History reads both operands back
    # through `closure_zone`, so the two can never be judged against different calendars.
    occ.completed_timezone = str(tz)
    await session.flush()

    # Anchor the successor to the occurrence just cleared (skip-missed applied), so its
    # due date advances one interval on the grid rather than from the completion time.
    # An unscheduled chore has no grid and reopens at the completion moment instead.
    rule = rule_for(chore)
    upcoming = next_occurrence_after(scheduled_for, completed_at, rule, tz)
    if chore.repeats != RepeatPeriod.manual:
        # Walk past any slot this chore has already completed. Unconditional rather than
        # gated on `backdate`, because it is the identity whenever nothing collides and
        # gating it would leave the same latent bug on the just-now path. It only became
        # reachable with backdating: the successor can now land on or before today, so a
        # chore whose open slot was re-seeded into the past (the unscheduled -> scheduled
        # round trip) can walk onto a done row, and `uq_occurrence_chore_scheduled` would
        # turn that into a 409 no retry could ever clear.
        #
        # `manual` is skipped because it has no grid: its successor is the completion instant
        # rather than a slot, so every done row sits at an earlier instant and the walk would
        # be the identity. Skipping it saves the query rather than avoiding a raise - the
        # `next_slot_after` inside would be unreachable even if this ran.
        upcoming = await free_slot_from(session, chore.id, upcoming, rule, tz)
    pool = list(chore.assignees)
    next_person = (
        await _retained_assignee(session, chore, occ.assignee_id, pool)
        if skipped
        else await _successor_assignee(session, chore, occ.assignee_id, pool)
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
        # re-close the same slot); the unique guards turn that into a 409, not a 500. Since
        # `free_slot_from` above, this is the *only* thing left that can land here, so the
        # 409 now genuinely means "somebody else got there first" rather than "this edit
        # recomputed an occupied slot". Not demonstrable under the savepoint fixtures, which
        # give each test one connection.
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflict_detail) from None

    # The real `now`, never the backdated instant: see the docstring.
    days = days_until_due(upcoming, now, tz)
    return CompletionRead(
        id=completion_id,
        chore_id=chore.id,
        title=completion_title,
        scheduled_for=scheduled_for,
        completed_by_user_id=closed_by_id,
        skipped=skipped,
        created_at=completed_at,
        next_due=upcoming,
        days_until_due=days,
        status=due_status(days),
    )


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
    one of the chore's assignees; the assignee pool is never modified.

    An optional `backdate` records the completion against the occurrence's own due day
    instead of now, for the chore that was done and not ticked: it reads as on time, and the
    successor advances one slot rather than jumping past everything that was missed, so a
    backlog is walked one completion at a time. Refused for an unscheduled chore, below."""
    chore = await _get_user_chore_or_404(session, user, chore_id)
    if payload is not None and payload.backdate and chore.repeats == RepeatPeriod.manual:
        # Placed here, before the occurrence lookup and before the credit check, for the same
        # reason skip_chore's twin is: it is a property of the *target*, so every caller gets
        # the same actionable answer rather than one about their own request.
        #
        # Refused rather than ignored because an unscheduled chore reopens AT its completion
        # moment (`next_occurrence_after` returns it verbatim), so a backdated one would
        # reopen at the end of a day - and doing the chore twice in one day would recompute
        # the identical instant and collide on `uq_occurrence_chore_scheduled`, a 409 no
        # retry could clear. There is nothing to record it against anyway: those chores are
        # never due, and their `scheduled_for` reads as "open since", not a deadline.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An unscheduled chore is never due, so there is nothing to backdate",
        )
    occ = await _open_occurrence(session, chore.id)
    if occ is None:
        # Nothing open to complete. Not reachable by simply completing twice (the successor
        # is unconditional), but a concurrent undo can clear the slot mid-request, and
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
    return await _close_occurrence(
        session,
        chore,
        occ,
        closed_by_id=completed_by_id,
        skipped=False,
        backdate=payload is not None and payload.backdate,
        conflict_detail="This chore has already been completed",
    )


@router.post("/{chore_id}/skip", response_model=CompletionRead, status_code=status.HTTP_201_CREATED)
async def skip_chore(chore_id: int, user: CurrentUser, session: SessionDep) -> CompletionRead:
    """Skip a chore's current occurrence: close it and move the chore on to its next slot
    without recording any work. Ungated like completing, since every role that can complete a
    chore can decide not to do one.

    Two things it deliberately is not. It takes no `completed_by_user_id`, because there is no
    credit to hand out - a skip is always recorded against whoever pressed the button. And it
    refuses an unscheduled chore (400): those are never due, so there is no deadline to move
    past and nothing to skip. That refusal is also what keeps "every skipped row belongs to a
    scheduled chore" true at the data layer rather than only in the UI, which is what lets the
    punctuality breakdown in stats.py host a skipped slice alongside its three due-date ones.

    Deliberately UNBOUNDED, as a recorded decision rather than an oversight: nothing checks
    that the occurrence is actually due, so a chore can be skipped repeatedly and pushed
    arbitrarily far forward, and skipping somebody else's chore moves their deadline with no
    notification. That is exactly the latitude completing already has (nothing stops you
    completing a chore weeks early either), every skip leaves a history row naming who did it,
    and Home only ever surfaces overdue/today/soon, so a pushed-out chore simply leaves the
    view. Bounding it would need a notion of "too early" that the completion path does not
    have; if that is ever wanted, both paths should get it together.
    """
    chore = await _get_user_chore_or_404(session, user, chore_id)
    if chore.repeats == RepeatPeriod.manual:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An unscheduled chore is never due, so there is nothing to skip",
        )
    occ = await _open_occurrence(session, chore.id)
    if occ is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This chore has no open occurrence to skip",
        )
    return await _close_occurrence(
        session,
        chore,
        occ,
        closed_by_id=user.id,
        skipped=True,
        # Explicit rather than defaulted, so the decision is greppable: a skip records no
        # work, so there is nothing to date on a due day and no "I did it on Friday" to tell
        # apart from "I gave up on Friday". Its own missed-slot swallowing stands.
        backdate=False,
        # Not the pre-check's wording: reaching this means the slot WAS open and a concurrent
        # request closed it underneath us, so "nothing to skip" would describe the wrong event.
        conflict_detail="This chore has already been closed",
    )

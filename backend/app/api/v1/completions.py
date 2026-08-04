from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select

from app.api.deps import CurrentUser, Impersonator, SessionDep
from app.api.v1.households import SortDir
from app.core.chores import days_late
from app.core.household_log import record_log_entry
from app.core.households import member_household_ids, role_in_household, roles_at_least
from app.models import (
    Chore,
    ChoreOccurrence,
    Household,
    HouseholdLogAction,
    HouseholdRole,
    OccurrenceStatus,
    RepeatPeriod,
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

# Which kind of closure to list. Omitted means both, matching the empty-means-unset
# convention the frontend's table hook already uses for its other filters.
CompletionOutcome = Literal["completed", "skipped"]


@router.get("/filters", response_model=HistoryFilterOptions)
async def completion_filters(user: CurrentUser, session: SessionDep) -> HistoryFilterOptions:
    """The option lists for the History filters: the households the user belongs
    to, and the distinct active members across them (candidate completers).

    Deliberately NOT narrowed by role, unlike the history list right below it. This
    endpoint also feeds the filter bars on Home and Unscheduled (see
    `frontend/src/components/chores/useFilterOptions.ts`), which every role uses, so
    restricting it to deputies would empty the household and member pickers there. Note
    that makes it a superset of what History can show a helper (their own closures only),
    which is why History hides its filter bar entirely rather than narrowing this. It
    exposes household names and member names, both of which every member already sees on
    Home."""
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
    outcome: CompletionOutcome | None = None,
) -> Page[HistoryEntryRead]:
    """Chore history across every active household the caller belongs to, narrowed per
    household by their role: where they are at least a deputy they see everybody's closures,
    where they are only a helper they see their own and nothing else. Reads the `done`
    occurrences of the merged occurrences table, which is both real completions and skips:
    each entry carries `skipped` so the list can tell them apart, and `outcome` narrows to
    one kind. Optional user_id / household_id narrow the list too; a household they do not
    belong to, or a stranger's id in a household they are only a helper in, yields an empty
    page rather than a 403, since the list spans every household at once. History of
    soft-deleted chores is kept (the title is snapshotted for exactly this and the chore row
    still resolves the join)."""
    # An occurrence has no household_id of its own, so scope by joining to the chore
    # and filtering on its household. No Chore.deleted_at filter: history outlives a
    # soft-deleted chore.
    #
    # The or_ lives in `filters`, which the count query below shares: applied to the page
    # query alone it would narrow the rows while `total` still counted the household's whole
    # history, and the pager would offer pages that come back empty.
    filters = [
        ChoreOccurrence.status == OccurrenceStatus.done,
        or_(
            # Deputy or better: everybody's closures, housemates' included.
            Chore.household_id.in_(member_household_ids(user.id, HouseholdRole.deputy)),
            # Any membership at all, own closures only. This is what a helper's History is:
            # the chores they ticked off themselves. The overlap with the branch above is
            # harmless, and the membership check is what keeps a stranger's household out.
            and_(
                Chore.household_id.in_(member_household_ids(user.id)),
                ChoreOccurrence.completed_by_user_id == user.id,
            ),
        ),
    ]
    if household_id is not None:
        filters.append(Chore.household_id == household_id)
    if user_id is not None:
        filters.append(ChoreOccurrence.completed_by_user_id == user_id)
    if outcome is not None:
        filters.append(ChoreOccurrence.skipped.is_(outcome == "skipped"))

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
        # Chore.repeats rides along so lateness can be suppressed for the unscheduled ones;
        # the chore is joined for scoping anyway, so this costs nothing.
        select(ChoreOccurrence, Household, User, Chore.repeats)
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
            skipped=occ.skipped,
            # An unscheduled chore has no deadline, so it can be neither late nor on time.
            # Nor can a skip: it had a deadline, but nothing was done to be punctual about,
            # and reporting "3 days late" against work that never happened would read as a
            # completion. Both land on the same `history.notDue` placeholder in the table.
            days_late=(
                None
                if repeats == RepeatPeriod.manual or occ.skipped
                else days_late(occ.scheduled_for, occ.completed_at)
            ),
            completed_by=HouseholdMemberRead.model_validate(completer) if completer else None,
            household=ChoreHouseholdRead.model_validate(household),
        )
        for occ, household, completer, repeats in result.all()
    ]
    return Page[HistoryEntryRead](items=items, total=total, page=page, page_size=page_size)


@router.delete("/{completion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def undo_completion(
    completion_id: int, user: CurrentUser, session: SessionDep, impersonator: Impersonator
) -> None:
    """Undo a closure, completion or skip alike (identified by its done-occurrence id).
    Either the user it is recorded against (completed_by) or an organiser of that household
    may undo it. Both halves matter: the occurrence stores no separate record of who
    submitted it, so somebody who completes a chore on another member's behalf cannot undo
    it themselves, and before the organiser half existed a helper's closure could be undone
    by nobody at all.
    Undoing the chore's latest closure (the most recently *closed* one, see below)
    reopens that occurrence (deleting the successor open occurrence first) so the chore is
    available again with its original assignee; undoing an older one just removes that
    history row. A skip counts as a closure for "latest" here, because it really did close
    its slot and its successor really is the open row. Note that reopening rolls a rotating
    chore's turn back, so an organiser undoing a housemate's closure can move work between
    people - deliberately, since fixing a mis-skip is the point."""
    # Scope to the households the caller belongs to at all, whatever their role: a done
    # occurrence outside it, or a missing id, is a 404. Plain membership rather than the
    # deputy scope because a helper reaches History for their own closures now, so a 404 on
    # a row they can see would be the lie the "reads narrow, writes 403" rule warns about.
    # The household id rides along for the role check below rather than costing a query.
    row = (
        await session.execute(
            select(ChoreOccurrence, Chore.household_id)
            .join(Chore, Chore.id == ChoreOccurrence.chore_id)
            .where(
                ChoreOccurrence.id == completion_id,
                ChoreOccurrence.status == OccurrenceStatus.done,
                Chore.household_id.in_(member_household_ids(user.id)),
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Completion not found")
    occ, household_id = row
    if occ.completed_by_user_id != user.id:
        # Asked only once the self-rule has failed, so the common path stays one query.
        # Hand-raised rather than `require_role`, whose "Only household organisers can do
        # this" would be a lie: the deputy who recorded this closure can undo it. The rule is
        # a disjunction, so the message has to name both halves. The owner passes here on
        # their membership row, which a transfer always promotes to organiser - not on
        # admin_id, which this deliberately never reads.
        role = await role_in_household(session, household_id, user.id)
        if role is None or role not in roles_at_least(HouseholdRole.organiser):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only undo your own entries unless you are a household organiser",
            )

    # Everything the household log needs, read NOW and never off `occ` again: both branches
    # below destroy it. Reopening nulls the title, the completer and the completion time and
    # clears `skipped`; an older closure is deleted outright. Which is also why the log holds
    # no reference to the occurrence itself - there is no `ondelete` that survives both paths.
    logged_chore_id = occ.chore_id
    logged_title = occ.title
    logged_target_id = occ.completed_by_user_id
    logged_action = (
        HouseholdLogAction.skip_undone if occ.skipped else HouseholdLogAction.completion_undone
    )

    # Is this the chore's most recent completion? Ordered by `completed_at`, NOT by
    # `scheduled_for`: slots only run in completion order while they come off a recurrence
    # grid, and an unscheduled chore's successor is anchored at the moment it was completed.
    # A chore switched to unscheduled while its slot was still in the future therefore ends
    # up with a done row dated later than the open row that follows it, and ordering by slot
    # would call the wrong completion the latest - reopening a future slot with a stale
    # assignee while deleting the live open occurrence. `max` ignores NULLs, and no
    # production path writes a done row without a completion time.
    latest_completed_at = await session.scalar(
        select(func.max(ChoreOccurrence.completed_at)).where(
            ChoreOccurrence.chore_id == occ.chore_id,
            ChoreOccurrence.status == OccurrenceStatus.done,
        )
    )
    if occ.completed_at is not None and occ.completed_at == latest_completed_at:
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
        # Clearing `skipped` matters as much as the rest: an open row that kept the flag
        # would be completed for real later and still land in history as a skip, since
        # nothing downstream re-derives it.
        occ.skipped = False
    else:
        # An older completion: a history edit, the current open occurrence stands.
        await session.delete(occ)
    await record_log_entry(
        session,
        action=logged_action,
        household_id=household_id,
        actor_id=user.id,
        chore_id=logged_chore_id,
        chore_title=logged_title,
        target_id=logged_target_id,
        impersonator_id=impersonator.id if impersonator else None,
    )
    await session.commit()
